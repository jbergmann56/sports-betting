"""
Database Manager for Multi-Sport Betting Tracker
Handles all MySQL operations with Azure MySQL
"""

import mysql.connector
from mysql.connector import Error
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date
import pandas as pd
from contextlib import contextmanager
import logging

from config import DB_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages all database operations"""
    
    def __init__(self, config: Dict = None):
        self.config = config or DB_CONFIG
        self.connection = None
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = mysql.connector.connect(**self.config)
            yield conn
            conn.commit()
        except Error as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        """Execute a query and optionally fetch results"""
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params or ())
            
            if fetch:
                return cursor.fetchall()
            return cursor.lastrowid
    
    def execute_many(self, query: str, data: List[tuple]):
        """Execute bulk insert/update"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, data)
            return cursor.rowcount
    
    # ============================================
    # SPORT OPERATIONS
    # ============================================
    
    def get_sport_id(self, sport_abbrev: str) -> Optional[int]:
        """Get sport ID by abbreviation"""
        query = "SELECT sport_id FROM sports WHERE sport_abbrev = %s"
        result = self.execute_query(query, (sport_abbrev,), fetch=True)
        return result[0]['sport_id'] if result else None
    
    def get_all_sports(self) -> List[Dict]:
        """Get all active sports"""
        query = "SELECT * FROM sports WHERE active = TRUE"
        return self.execute_query(query, fetch=True)
    
    # ============================================
    # TEAM OPERATIONS
    # ============================================
    
    def get_or_create_team(self, team_name: str, sport_abbrev: str, 
                           city: str = None, abbrev: str = None) -> int:
        """Get existing team or create new one"""
        sport_id = self.get_sport_id(sport_abbrev)
        
        # Try to find existing team
        query = """
            SELECT team_id FROM teams 
            WHERE team_name = %s AND sport_id = %s
        """
        result = self.execute_query(query, (team_name, sport_id), fetch=True)
        
        if result:
            return result[0]['team_id']
        
        # Create new team
        insert_query = """
            INSERT INTO teams (sport_id, team_name, team_abbrev, city)
            VALUES (%s, %s, %s, %s)
        """
        return self.execute_query(insert_query, (sport_id, team_name, abbrev, city))
    
    def get_teams_by_sport(self, sport_abbrev: str) -> List[Dict]:
        """Get all teams for a sport"""
        sport_id = self.get_sport_id(sport_abbrev)
        query = """
            SELECT team_id, team_name, team_abbrev, city
            FROM teams
            WHERE sport_id = %s AND active = TRUE
            ORDER BY team_name
        """
        return self.execute_query(query, (sport_id,), fetch=True)
    
    # ============================================
    # GAME OPERATIONS
    # ============================================
    
    def create_game(self, sport_abbrev: str, game_date: date, 
                   game_time: Optional[str], home_team_name: str, 
                   away_team_name: str, season_year: int = None,
                   week_number: int = None) -> int:
        """Create a new game"""
        sport_id = self.get_sport_id(sport_abbrev)
        home_team_id = self.get_or_create_team(home_team_name, sport_abbrev)
        away_team_id = self.get_or_create_team(away_team_name, sport_abbrev)
        
        # Combine date and time if time provided
        game_datetime = None
        if game_time:
            try:
                time_obj = datetime.strptime(game_time, '%H:%M:%S').time()
                game_datetime = datetime.combine(game_date, time_obj)
            except:
                pass
        
        query = """
            INSERT INTO games 
            (sport_id, game_date, game_time, game_datetime, home_team_id, 
             away_team_id, season_year, week_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (sport_id, game_date, game_time, game_datetime, 
                 home_team_id, away_team_id, season_year, week_number)
        
        return self.execute_query(query, params)
    
    def get_games_by_date(self, sport_abbrev: str, game_date: date) -> List[Dict]:
        """Get all games for a specific date"""
        sport_id = self.get_sport_id(sport_abbrev)
        query = """
            SELECT g.game_id, g.game_date, g.game_time,
                   ht.team_name as home_team, at.team_name as away_team,
                   g.home_score, g.away_score, g.game_status
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.team_id
            JOIN teams at ON g.away_team_id = at.team_id
            WHERE g.sport_id = %s AND g.game_date = %s
            ORDER BY g.game_time
        """
        return self.execute_query(query, (sport_id, game_date), fetch=True)
    
    def update_game_score(self, game_id: int, home_score: int, 
                         away_score: int, overtime: bool = False):
        """Update game scores and status"""
        query = """
            UPDATE games 
            SET home_score = %s, away_score = %s, game_status = 'final',
                overtime = %s, updated_at = NOW()
            WHERE game_id = %s
        """
        self.execute_query(query, (home_score, away_score, overtime, game_id))
    
    def get_game_by_teams_date(self, sport_abbrev: str, home_team: str,
                              away_team: str, game_date: date) -> Optional[int]:
        """Find game by teams and date (avoid duplicates)"""
        sport_id = self.get_sport_id(sport_abbrev)
        query = """
            SELECT g.game_id
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.team_id
            JOIN teams at ON g.away_team_id = at.team_id
            WHERE g.sport_id = %s 
                AND ht.team_name = %s 
                AND at.team_name = %s
                AND g.game_date = %s
        """
        result = self.execute_query(query, (sport_id, home_team, away_team, game_date), 
                                   fetch=True)
        return result[0]['game_id'] if result else None
    
    # ============================================
    # ODDS OPERATIONS
    # ============================================
    
    def insert_odds(self, game_id: int, odds_type: str, side: str,
                   line_value: float = None, american_odds: int = None,
                   source: str = 'bovada'):
        """Insert odds for a game"""
        # Calculate decimal odds and implied probability
        decimal_odds = None
        implied_prob = None
        
        if american_odds:
            if american_odds > 0:
                decimal_odds = (american_odds / 100) + 1
                implied_prob = 100 / (american_odds + 100)
            else:
                decimal_odds = (100 / abs(american_odds)) + 1
                implied_prob = abs(american_odds) / (abs(american_odds) + 100)
        
        query = """
            INSERT INTO odds 
            (game_id, odds_type, side, line_value, american_odds, 
             decimal_odds, implied_probability, source, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        params = (game_id, odds_type, side, line_value, american_odds,
                 decimal_odds, implied_prob, source)
        
        return self.execute_query(query, params)
    
    def get_latest_odds(self, game_id: int) -> Dict:
        """Get the latest odds for a game"""
        query = """
            SELECT odds_type, side, line_value, american_odds, decimal_odds
            FROM odds
            WHERE game_id = %s
            ORDER BY timestamp DESC
        """
        results = self.execute_query(query, (game_id,), fetch=True)
        
        # Organize by odds type
        odds_dict = {'spread': {}, 'moneyline': {}, 'over_under': {}}
        for row in results:
            odds_type = row['odds_type']
            side = row['side']
            if odds_type not in odds_dict[odds_type] or side not in odds_dict[odds_type]:
                odds_dict[odds_type][side] = row
        
        return odds_dict
    
    # ============================================
    # BET OPERATIONS
    # ============================================
    
    def place_bet(self, game_id: int, bet_type: str, side: str,
                 bet_amount: float, line_value: float, american_odds: int,
                 strategy: str = None, notes: str = None) -> int:
        """Record a bet"""
        # Calculate decimal odds and potential return
        if american_odds > 0:
            decimal_odds = (american_odds / 100) + 1
        else:
            decimal_odds = (100 / abs(american_odds)) + 1
        
        potential_return = bet_amount * decimal_odds
        
        query = """
            INSERT INTO bets
            (game_id, bet_type, side, bet_amount, line_value, american_odds,
             decimal_odds, potential_return, result, strategy, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
        """
        params = (game_id, bet_type, side, bet_amount, line_value,
                 american_odds, decimal_odds, potential_return, strategy, notes)
        
        return self.execute_query(query, params)
    
    def update_bet_result(self, bet_id: int, result: str, 
                         actual_return: float = None):
        """Update bet result after game completes"""
        query = """
            UPDATE bets
            SET result = %s, actual_return = %s,
                profit_loss = %s - bet_amount
            WHERE bet_id = %s
        """
        self.execute_query(query, (result, actual_return or 0, 
                                  actual_return or 0, bet_id))
    
    def get_pending_bets(self, sport_abbrev: str = None) -> List[Dict]:
        """Get all pending bets"""
        if sport_abbrev:
            sport_id = self.get_sport_id(sport_abbrev)
            query = """
                SELECT b.bet_id, b.bet_type, b.side, b.bet_amount, b.line_value,
                       b.american_odds, b.potential_return, g.game_date,
                       ht.team_name as home_team, at.team_name as away_team
                FROM bets b
                JOIN games g ON b.game_id = g.game_id
                JOIN teams ht ON g.home_team_id = ht.team_id
                JOIN teams at ON g.away_team_id = at.team_id
                WHERE b.result = 'pending' AND g.sport_id = %s
                ORDER BY g.game_date, g.game_time
            """
            return self.execute_query(query, (sport_id,), fetch=True)
        else:
            query = """
                SELECT b.bet_id, b.bet_type, b.side, b.bet_amount, b.line_value,
                       b.american_odds, b.potential_return, g.game_date,
                       ht.team_name as home_team, at.team_name as away_team,
                       s.sport_abbrev
                FROM bets b
                JOIN games g ON b.game_id = g.game_id
                JOIN teams ht ON g.home_team_id = ht.team_id
                JOIN teams at ON g.away_team_id = at.team_id
                JOIN sports s ON g.sport_id = s.sport_id
                WHERE b.result = 'pending'
                ORDER BY g.game_date, g.game_time
            """
            return self.execute_query(query, fetch=True)
    
    def get_bet_performance(self, sport_abbrev: str = None, 
                          start_date: date = None, end_date: date = None) -> pd.DataFrame:
        """Get betting performance analytics"""
        conditions = ["b.result != 'pending'"]
        params = []
        
        if sport_abbrev:
            sport_id = self.get_sport_id(sport_abbrev)
            conditions.append("g.sport_id = %s")
            params.append(sport_id)
        
        if start_date:
            conditions.append("g.game_date >= %s")
            params.append(start_date)
        
        if end_date:
            conditions.append("g.game_date <= %s")
            params.append(end_date)
        
        where_clause = " AND ".join(conditions)
        
        query = f"""
            SELECT b.*, g.game_date, 
                   ht.team_name as home_team, at.team_name as away_team,
                   s.sport_abbrev, g.home_score, g.away_score
            FROM bets b
            JOIN games g ON b.game_id = g.game_id
            JOIN teams ht ON g.home_team_id = ht.team_id
            JOIN teams at ON g.away_team_id = at.team_id
            JOIN sports s ON g.sport_id = s.sport_id
            WHERE {where_clause}
            ORDER BY g.game_date DESC
        """
        
        results = self.execute_query(query, tuple(params), fetch=True)
        return pd.DataFrame(results)
    
    # ============================================
    # TEAM RATINGS OPERATIONS
    # ============================================
    
    def insert_team_rating(self, team_name: str, sport_abbrev: str,
                          rating_date: date, rating_type: str,
                          rating_value: float, rank: int = None,
                          source: str = None):
        """Insert or update team rating"""
        team_id = self.get_or_create_team(team_name, sport_abbrev)
        
        query = """
            INSERT INTO team_ratings
            (team_id, rating_date, rating_type, rating_value, rank, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rating_value = VALUES(rating_value),
                rank = VALUES(rank)
        """
        params = (team_id, rating_date, rating_type, rating_value, rank, source)
        self.execute_query(query, params)
    
    def get_latest_team_ratings(self, sport_abbrev: str, 
                               rating_type: str = 'SRS') -> pd.DataFrame:
        """Get latest ratings for all teams in a sport"""
        sport_id = self.get_sport_id(sport_abbrev)
        
        query = """
            SELECT t.team_name, tr.rating_value, tr.rank, tr.rating_date
            FROM team_ratings tr
            JOIN teams t ON tr.team_id = t.team_id
            WHERE t.sport_id = %s AND tr.rating_type = %s
                AND tr.rating_date = (
                    SELECT MAX(rating_date) 
                    FROM team_ratings 
                    WHERE team_id = tr.team_id AND rating_type = %s
                )
            ORDER BY tr.rating_value DESC
        """
        results = self.execute_query(query, (sport_id, rating_type, rating_type), 
                                    fetch=True)
        return pd.DataFrame(results)
