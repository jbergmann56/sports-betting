"""
Historical Data Importer
Import existing Excel betting data into MySQL database
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Dict, List
import logging

from database import DatabaseManager
from config import SPORT_CONFIGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HistoricalDataImporter:
    """Import historical betting data from Excel files"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def import_nhl_excel(self, file_path: str) -> Dict[str, int]:
        """
        Import NHL betting data from the provided Excel format
        Returns counts of imported records
        """
        logger.info(f"Importing NHL data from {file_path}")
        
        counts = {
            'games': 0,
            'odds': 0,
            'bets': 0,
            'ratings': 0,
            'errors': 0
        }
        
        try:
            # Read main sheet
            df = pd.read_excel(file_path, sheet_name='NHL_DB_Gamble_Excel')
            
            # Clean column names
            df.columns = df.columns.str.strip()
            
            # Process each row
            for idx, row in df.iterrows():
                try:
                    # Skip if no date
                    if pd.isna(row.get('Date')):
                        continue
                    
                    # Parse date
                    game_date = pd.to_datetime(row['Date']).date()
                    
                    # Get team names
                    away_team = row.get('Away')
                    home_team = row.get('Home')
                    
                    if pd.isna(away_team) or pd.isna(home_team):
                        continue
                    
                    # Parse time if available
                    game_time = None
                    if 'Time' in row and not pd.isna(row['Time']):
                        try:
                            if isinstance(row['Time'], str):
                                game_time = datetime.strptime(row['Time'], '%H:%M:%S').time().strftime('%H:%M:%S')
                            else:
                                game_time = row['Time'].strftime('%H:%M:%S')
                        except:
                            pass
                    
                    # Get week and year
                    week = row.get('WEEK')
                    year = row.get('Year')
                    
                    # Check if game exists
                    game_id = self.db.get_game_by_teams_date('NHL', home_team, away_team, game_date)
                    
                    if not game_id:
                        # Create game
                        game_id = self.db.create_game(
                            'NHL', game_date, game_time, home_team, away_team,
                            season_year=year if not pd.isna(year) else None,
                            week_number=week if not pd.isna(week) else None
                        )
                        counts['games'] += 1
                    
                    # Update scores if available
                    if not pd.isna(row.get('Away Score')) and not pd.isna(row.get('Home Score')):
                        away_score = int(row['Away Score'])
                        home_score = int(row['Home Score'])
                        overtime = row.get('OT', False) == True or row.get('OT') == 1
                        
                        self.db.update_game_score(game_id, home_score, away_score, overtime)
                    
                    # Import odds
                    # Spread
                    if not pd.isna(row.get('Away Puck Line')) and not pd.isna(row.get('Away Odds')):
                        away_line = float(row['Away Puck Line'])
                        away_odds = int(row['Away Odds'])
                        self.db.insert_odds(game_id, 'spread', 'away', away_line, away_odds, source='historical')
                        counts['odds'] += 1
                    
                    if not pd.isna(row.get('Home Puck Line')) and not pd.isna(row.get('Home Odds')):
                        home_line = float(row['Home Puck Line'])
                        home_odds = int(row['Home Odds'])
                        self.db.insert_odds(game_id, 'spread', 'home', home_line, home_odds, source='historical')
                        counts['odds'] += 1
                    
                    # Over/Under
                    if not pd.isna(row.get('Over Under')) and not pd.isna(row.get('OU Odds')):
                        ou_line = float(row['Over Under'])
                        ou_odds = int(row['OU Odds'])
                        # Typically same odds for over/under, split them
                        self.db.insert_odds(game_id, 'over_under', 'over', ou_line, ou_odds, source='historical')
                        self.db.insert_odds(game_id, 'over_under', 'under', ou_line, ou_odds, source='historical')
                        counts['odds'] += 2
                    
                    # Import bets if placed
                    if not pd.isna(row.get('My Bet')) and row['My Bet'] == 1:
                        bet_amount = row.get('BET $', 0)
                        if not pd.isna(bet_amount) and bet_amount > 0:
                            # Determine bet type and side based on your logic
                            # This is simplified - you may need to adjust based on your Excel structure
                            bet_type = 'spread'  # Default, adjust as needed
                            side = 'away' if row.get('Away Est Spread', 0) > 0 else 'home'
                            line_value = float(row.get('Away Puck Line', 0))
                            odds = int(row.get('Away Odds', -110))
                            
                            bet_id = self.db.place_bet(
                                game_id, bet_type, side, bet_amount, 
                                line_value, odds, strategy='historical'
                            )
                            
                            # Update result if game is complete
                            if not pd.isna(row.get('Net $')):
                                net = float(row['Net $'])
                                if net > 0:
                                    result = 'win'
                                    actual_return = bet_amount + net
                                elif net < 0:
                                    result = 'loss'
                                    actual_return = 0
                                else:
                                    result = 'push'
                                    actual_return = bet_amount
                                
                                self.db.update_bet_result(bet_id, result, actual_return)
                            
                            counts['bets'] += 1
                    
                    # Import SRS ratings if available
                    if not pd.isna(row.get('Away SRS')):
                        self.db.insert_team_rating(
                            away_team, 'NHL', game_date, 'SRS',
                            float(row['Away SRS']), source='historical'
                        )
                        counts['ratings'] += 1
                    
                    if not pd.isna(row.get('Home SRS')):
                        self.db.insert_team_rating(
                            home_team, 'NHL', game_date, 'SRS',
                            float(row['Home SRS']), source='historical'
                        )
                        counts['ratings'] += 1
                
                except Exception as e:
                    logger.error(f"Error processing row {idx}: {e}")
                    counts['errors'] += 1
                    continue
            
            logger.info(f"Import complete: {counts}")
            return counts
        
        except Exception as e:
            logger.error(f"Error importing file: {e}")
            raise
    
    def import_generic_excel(self, file_path: str, sport: str, 
                           sheet_name: str = None) -> Dict[str, int]:
        """
        Generic importer for other sports with similar Excel structure
        Adapt field mappings as needed
        """
        logger.info(f"Importing {sport} data from {file_path}")
        
        counts = {
            'games': 0,
            'odds': 0,
            'bets': 0,
            'errors': 0
        }
        
        # Read Excel
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(file_path)
        
        # This is a template - adjust column mappings based on actual structure
        column_mapping = {
            'Date': 'date',
            'Away': 'away_team',
            'Home': 'home_team',
            'Away Score': 'away_score',
            'Home Score': 'home_score',
            # Add more mappings as needed
        }
        
        for idx, row in df.iterrows():
            try:
                # Extract and process data similar to NHL import
                # Adjust based on actual Excel structure
                pass
            except Exception as e:
                logger.error(f"Error processing row {idx}: {e}")
                counts['errors'] += 1
        
        return counts
    
    def bulk_import_directory(self, directory_path: str, 
                            sport_file_mapping: Dict[str, str]) -> Dict[str, Dict]:
        """
        Import multiple Excel files from a directory
        
        Args:
            directory_path: Path to directory with Excel files
            sport_file_mapping: Dict mapping sport abbrev to filename
                e.g., {'NHL': 'nhl_data.xlsx', 'NBA': 'nba_data.xlsx'}
        
        Returns:
            Dict of results for each sport
        """
        import os
        
        results = {}
        
        for sport, filename in sport_file_mapping.items():
            file_path = os.path.join(directory_path, filename)
            
            if not os.path.exists(file_path):
                logger.warning(f"File not found: {file_path}")
                continue
            
            try:
                if sport == 'NHL':
                    counts = self.import_nhl_excel(file_path)
                else:
                    counts = self.import_generic_excel(file_path, sport)
                
                results[sport] = counts
                logger.info(f"Completed {sport} import: {counts}")
            
            except Exception as e:
                logger.error(f"Error importing {sport}: {e}")
                results[sport] = {'error': str(e)}
        
        return results


def demo_import():
    """Demo the importer"""
    db = DatabaseManager()
    importer = HistoricalDataImporter(db)
    
    # Import NHL data
    file_path = '/mnt/user-data/uploads/NHL_DB_Gamble_Excel.xlsx'
    
    try:
        results = importer.import_nhl_excel(file_path)
        print("Import Results:")
        for key, count in results.items():
            print(f"  {key}: {count}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    demo_import()
