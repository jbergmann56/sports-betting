"""
Bovada Bulk Paste Parser
Intelligently parses copy/pasted text from Bovada website
"""

import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging

from config import TEAM_NAME_MAPPINGS, SPORT_CONFIGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ParsedGame:
    """Structured game data from Bovada paste"""
    sport: str
    game_date: date
    game_time: Optional[str]
    away_team: str
    home_team: str
    spread_away: Optional[float] = None
    spread_away_odds: Optional[int] = None
    spread_home: Optional[float] = None
    spread_home_odds: Optional[int] = None
    moneyline_away: Optional[int] = None
    moneyline_home: Optional[int] = None
    over_under: Optional[float] = None
    over_odds: Optional[int] = None
    under_odds: Optional[int] = None
    parse_warnings: List[str] = None
    
    def __post_init__(self):
        if self.parse_warnings is None:
            self.parse_warnings = []


class BovadaParser:
    """Parse bulk pasted text from Bovada"""
    
    def __init__(self, sport: str):
        self.sport = sport.upper()
        self.team_mappings = TEAM_NAME_MAPPINGS.get(self.sport, {})
    
    def parse_bulk_paste(self, text: str) -> List[ParsedGame]:
        """
        Parse bulk pasted text from Bovada
        
        Expected format (flexible):
        12/8/2024 7:00 PM
        Boston Bruins
        Pittsburgh Penguins
        Spread
        Boston Bruins -1.5 +180
        Pittsburgh Penguins +1.5 -225
        Total
        Over 6 -115
        Under 6 -105
        Money Line
        Boston Bruins -145
        Pittsburgh Penguins +125
        
        [Next game...]
        """
        games = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        i = 0
        while i < len(lines):
            try:
                game, lines_consumed = self._parse_single_game(lines[i:])
                if game:
                    games.append(game)
                    i += lines_consumed
                else:
                    i += 1
            except Exception as e:
                logger.warning(f"Error parsing at line {i}: {e}")
                i += 1
        
        return games
    
    def _parse_single_game(self, lines: List[str]) -> Tuple[Optional[ParsedGame], int]:
        """Parse a single game from lines starting at current position"""
        if not lines:
            return None, 0
        
        game = ParsedGame(sport=self.sport, game_date=None, game_time=None,
                         away_team=None, home_team=None)
        
        line_idx = 0
        
        # Parse date/time (first line should be date)
        date_match = re.search(r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', lines[line_idx])
        if date_match:
            game.game_date = self._parse_date(date_match.group(1))
            
            # Try to find time on same line
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', lines[line_idx], re.IGNORECASE)
            if time_match:
                game.game_time = self._parse_time(time_match.group(1))
            
            line_idx += 1
        else:
            game.parse_warnings.append("No date found")
            return None, 0
        
        # Next two lines should be team names (away, then home)
        if line_idx < len(lines):
            away_team = self._normalize_team_name(lines[line_idx])
            if away_team:
                game.away_team = away_team
                line_idx += 1
        
        if line_idx < len(lines):
            home_team = self._normalize_team_name(lines[line_idx])
            if home_team:
                game.home_team = home_team
                line_idx += 1
        
        if not game.away_team or not game.home_team:
            game.parse_warnings.append("Could not identify both teams")
            return None, line_idx
        
        # Parse odds sections (Spread, Total, Money Line)
        while line_idx < len(lines):
            line = lines[line_idx].lower()
            
            # Check if we hit the next game (new date)
            if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', lines[line_idx]):
                break
            
            if 'spread' in line or 'point spread' in line or 'puck line' in line:
                line_idx += 1
                # Parse spread lines
                spread_lines, consumed = self._parse_odds_section(lines[line_idx:], game, 'spread')
                line_idx += consumed
                
            elif 'total' in line or 'over/under' in line:
                line_idx += 1
                # Parse total lines
                total_lines, consumed = self._parse_odds_section(lines[line_idx:], game, 'total')
                line_idx += consumed
                
            elif 'money line' in line or 'moneyline' in line:
                line_idx += 1
                # Parse moneyline
                ml_lines, consumed = self._parse_odds_section(lines[line_idx:], game, 'moneyline')
                line_idx += consumed
                
            else:
                line_idx += 1
        
        return game, line_idx
    
    def _parse_odds_section(self, lines: List[str], game: ParsedGame, 
                           section_type: str) -> Tuple[List[str], int]:
        """Parse a section of odds (spread, total, or moneyline)"""
        parsed_lines = []
        line_idx = 0
        
        while line_idx < len(lines):
            line = lines[line_idx]
            
            # Stop if we hit next section or game
            if any(keyword in line.lower() for keyword in 
                   ['spread', 'total', 'money line', 'over/under']) and section_type != 'total':
                break
            
            if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', line):
                break
            
            if section_type == 'spread':
                self._parse_spread_line(line, game)
            elif section_type == 'total':
                self._parse_total_line(line, game)
            elif section_type == 'moneyline':
                self._parse_moneyline_line(line, game)
            
            parsed_lines.append(line)
            line_idx += 1
            
            # Limit to 4 lines per section to avoid over-consuming
            if line_idx >= 4:
                break
        
        return parsed_lines, line_idx
    
    def _parse_spread_line(self, line: str, game: ParsedGame):
        """Parse a spread line"""
        # Pattern: "Team Name -1.5 +180" or "Team Name +1.5 -110"
        match = re.search(r'([+\-]\d+\.?\d*)\s*([+\-]\d+)', line)
        if match:
            spread = float(match.group(1))
            odds = int(match.group(2))
            
            # Determine if this is away or home team
            away_in_line = any(word in line for word in game.away_team.split())
            home_in_line = any(word in line for word in game.home_team.split())
            
            if away_in_line:
                game.spread_away = spread
                game.spread_away_odds = odds
            elif home_in_line:
                game.spread_home = spread
                game.spread_home_odds = odds
    
    def _parse_total_line(self, line: str, game: ParsedGame):
        """Parse over/under line"""
        # Pattern: "Over 6 -115" or "Under 6.5 -105"
        if 'over' in line.lower():
            match = re.search(r'over\s*(\d+\.?\d*)\s*([+\-]\d+)', line, re.IGNORECASE)
            if match:
                game.over_under = float(match.group(1))
                game.over_odds = int(match.group(2))
        
        elif 'under' in line.lower():
            match = re.search(r'under\s*(\d+\.?\d*)\s*([+\-]\d+)', line, re.IGNORECASE)
            if match:
                if not game.over_under:  # Set O/U value if not already set
                    game.over_under = float(match.group(1))
                game.under_odds = int(match.group(2))
    
    def _parse_moneyline_line(self, line: str, game: ParsedGame):
        """Parse moneyline"""
        # Pattern: "Team Name -145" or "Team Name +125"
        match = re.search(r'([+\-]\d+)', line)
        if match:
            odds = int(match.group(1))
            
            away_in_line = any(word in line for word in game.away_team.split())
            home_in_line = any(word in line for word in game.home_team.split())
            
            if away_in_line:
                game.moneyline_away = odds
            elif home_in_line:
                game.moneyline_home = odds
    
    def _parse_date(self, date_str: str) -> date:
        """Parse date string in various formats"""
        # Try multiple formats
        formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y']
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        raise ValueError(f"Could not parse date: {date_str}")
    
    def _parse_time(self, time_str: str) -> str:
        """Parse time string and convert to 24-hour format"""
        time_str = time_str.strip()
        
        # Try to parse with AM/PM
        formats = ['%I:%M %p', '%I:%M%p', '%H:%M']
        
        for fmt in formats:
            try:
                time_obj = datetime.strptime(time_str, fmt).time()
                return time_obj.strftime('%H:%M:%S')
            except ValueError:
                continue
        
        return None
    
    def _normalize_team_name(self, team_str: str) -> Optional[str]:
        """Normalize team name using mappings"""
        team_str = team_str.strip()
        
        # Check if it's in our mappings
        if team_str in self.team_mappings:
            return self.team_mappings[team_str]
        
        # Check for partial matches
        for abbrev, full_name in self.team_mappings.items():
            if abbrev.lower() in team_str.lower() or team_str.lower() in full_name.lower():
                return full_name
        
        # Return as-is if no mapping found
        return team_str if len(team_str) > 2 else None
    
    def validate_game(self, game: ParsedGame) -> bool:
        """Validate parsed game data"""
        if not game.away_team or not game.home_team:
            game.parse_warnings.append("Missing team names")
            return False
        
        if not game.game_date:
            game.parse_warnings.append("Missing game date")
            return False
        
        # Check if at least one odds type is present
        has_odds = (game.spread_away is not None or 
                   game.moneyline_away is not None or 
                   game.over_under is not None)
        
        if not has_odds:
            game.parse_warnings.append("No odds found")
        
        return True


def demo_parser():
    """Demo the parser with sample text"""
    sample_text = """
    12/8/2024 7:00 PM
    Boston Bruins
    Pittsburgh Penguins
    Spread
    Boston Bruins -1.5 +180
    Pittsburgh Penguins +1.5 -225
    Total
    Over 6 -115
    Under 6 -105
    Money Line
    Boston Bruins -145
    Pittsburgh Penguins +125
    
    12/8/2024 8:00 PM
    Toronto Maple Leafs
    Tampa Bay Lightning
    Spread
    Toronto Maple Leafs -1.5 +165
    Tampa Bay Lightning +1.5 -200
    Total
    Over 6.5 -110
    Under 6.5 -110
    Money Line
    Toronto Maple Leafs -160
    Tampa Bay Lightning +140
    """
    
    parser = BovadaParser('NHL')
    games = parser.parse_bulk_paste(sample_text)
    
    print(f"Parsed {len(games)} games:\n")
    for i, game in enumerate(games, 1):
        print(f"Game {i}:")
        print(f"  Date: {game.game_date} at {game.game_time}")
        print(f"  {game.away_team} @ {game.home_team}")
        print(f"  Spread: {game.spread_away}/{game.spread_home} ({game.spread_away_odds}/{game.spread_home_odds})")
        print(f"  ML: {game.moneyline_away}/{game.moneyline_home}")
        print(f"  O/U: {game.over_under} ({game.over_odds}/{game.under_odds})")
        if game.parse_warnings:
            print(f"  Warnings: {game.parse_warnings}")
        print()


if __name__ == "__main__":
    demo_parser()
