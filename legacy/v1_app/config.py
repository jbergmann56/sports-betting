"""
MULTI-SPORT BETTING TRACKER
Configuration and constants
"""

import os
from dataclasses import dataclass
from typing import Dict, List

# Load environment variables from .env (local) or Streamlit secrets (cloud)
from pathlib import Path
from dotenv import load_dotenv

# Try to load from .env file (for local development)
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Helper function to get config values from either .env or Streamlit secrets
def get_secret(key: str, default=None):
    """Get secret from environment variable or Streamlit secrets"""
    # First try environment variables (from .env)
    value = os.getenv(key)
    if value:
        return value

    # Then try Streamlit secrets (for cloud deployment)
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except (ImportError, FileNotFoundError, KeyError):
        pass

    return default

# ============================================
# DATABASE CONFIGURATION
# ============================================
DB_CONFIG = {
    'host': get_secret('AZURE_MYSQL_HOST'),
    'user': get_secret('AZURE_MYSQL_USER'),
    'password': get_secret('AZURE_MYSQL_PASSWORD'),
    'database': get_secret('AZURE_MYSQL_DATABASE'),
    'port': int(get_secret('AZURE_MYSQL_PORT', '3306')),
}

# ============================================
# SPORT CONFIGURATIONS
# ============================================

@dataclass
class SportConfig:
    """Configuration for each sport"""
    name: str
    abbrev: str
    stat_source: str  # e.g., 'hockey-reference.com'
    primary_rating: str  # e.g., 'SRS', 'NET_RATING', 'ELO'
    api_endpoint: str = None
    has_overtime: bool = False
    typical_total_range: tuple = (0, 300)  # For validation


SPORT_CONFIGS: Dict[str, SportConfig] = {
    'NHL': SportConfig(
        name='Hockey',
        abbrev='NHL',
        stat_source='https://www.hockey-reference.com',
        primary_rating='SRS',
        api_endpoint='https://statsapi.web.nhl.com/api/v1',
        has_overtime=True,
        typical_total_range=(4, 8)
    ),
    'NBA': SportConfig(
        name='Basketball',
        abbrev='NBA',
        stat_source='https://www.basketball-reference.com',
        primary_rating='NET_RATING',
        api_endpoint='https://stats.nba.com/stats',
        has_overtime=True,
        typical_total_range=(180, 260)
    ),
    'NFL': SportConfig(
        name='Football',
        abbrev='NFL',
        stat_source='https://www.pro-football-reference.com',
        primary_rating='SRS',
        api_endpoint=None,
        has_overtime=True,
        typical_total_range=(30, 65)
    ),
    'MLB': SportConfig(
        name='Baseball',
        abbrev='MLB',
        stat_source='https://www.baseball-reference.com',
        primary_rating='PYTH_WIN_PCT',
        api_endpoint='https://statsapi.mlb.com/api/v1',
        has_overtime=False,
        typical_total_range=(6, 12)
    ),
}

# ============================================
# BOVADA PARSING PATTERNS
# ============================================

# Common team name variations for matching
TEAM_NAME_MAPPINGS = {
    'NHL': {
        # Handle common abbreviations and variations
        'LA': 'Los Angeles Kings',
        'L.A.': 'Los Angeles Kings',
        'NY Rangers': 'New York Rangers',
        'NYR': 'New York Rangers',
        'NY Islanders': 'New York Islanders',
        'NYI': 'New York Islanders',
        'TB': 'Tampa Bay Lightning',
        'VGK': 'Vegas Golden Knights',
        # Add more as needed
    },
    'NBA': {
        'LA Lakers': 'Los Angeles Lakers',
        'LA Clippers': 'Los Angeles Clippers',
        'NY Knicks': 'New York Knicks',
        'GS': 'Golden State Warriors',
        # Add more as needed
    },
    'NFL': {
        'KC': 'Kansas City Chiefs',
        'TB': 'Tampa Bay Buccaneers',
        'LA': 'Los Angeles Rams',
        'LAC': 'Los Angeles Chargers',
        # Add more as needed
    }
}

# Bovada paste format examples for parsing
BOVADA_PASTE_EXAMPLES = {
    'NHL': """
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
    """,
    'NBA': """
        12/8/2024 8:00 PM
        Los Angeles Lakers
        Golden State Warriors
        Spread
        Lakers -5.5 -110
        Warriors +5.5 -110
        Total
        Over 228.5 -110
        Under 228.5 -110
        Money Line
        Lakers -220
        Warriors +180
    """
}

# ============================================
# KELLY CRITERION SETTINGS
# ============================================

KELLY_SETTINGS = {
    'fractional_kelly': 0.25,  # Use 1/4 Kelly for safety
    'max_bet_pct': 0.05,  # Never bet more than 5% of bankroll
    'min_edge': 0.02,  # Only bet if edge > 2%
    'default_bankroll': 3000,
}

# ============================================
# API RATE LIMITS
# ============================================

RATE_LIMITS = {
    'nhl_api': 1.0,  # seconds between requests
    'hockey_reference': 2.0,
    'basketball_reference': 2.0,
}
