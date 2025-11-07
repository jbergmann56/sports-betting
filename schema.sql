-- ============================================
-- MULTI-SPORT BETTING DATABASE SCHEMA
-- ============================================

-- Sports reference table
CREATE TABLE sports (
    sport_id INT AUTO_INCREMENT PRIMARY KEY,
    sport_name VARCHAR(50) NOT NULL UNIQUE,
    sport_abbrev VARCHAR(10) NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Teams table (multi-sport)
CREATE TABLE teams (
    team_id INT AUTO_INCREMENT PRIMARY KEY,
    sport_id INT NOT NULL,
    team_name VARCHAR(100) NOT NULL,
    team_abbrev VARCHAR(10),
    city VARCHAR(100),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sport_id) REFERENCES sports(sport_id),
    UNIQUE KEY unique_team_sport (team_name, sport_id)
);

-- Games table
CREATE TABLE games (
    game_id INT AUTO_INCREMENT PRIMARY KEY,
    sport_id INT NOT NULL,
    game_date DATE NOT NULL,
    game_time TIME,
    game_datetime DATETIME,
    home_team_id INT NOT NULL,
    away_team_id INT NOT NULL,
    home_score INT,
    away_score INT,
    game_status ENUM('scheduled', 'in_progress', 'final', 'postponed', 'cancelled') DEFAULT 'scheduled',
    overtime BOOLEAN DEFAULT FALSE,
    season_year INT,
    week_number INT,
    external_game_id VARCHAR(100), -- For API reference
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (sport_id) REFERENCES sports(sport_id),
    FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
    FOREIGN KEY (away_team_id) REFERENCES teams(team_id),
    INDEX idx_game_date (game_date),
    INDEX idx_game_datetime (game_datetime)
);

-- Odds table (for all bet types)
CREATE TABLE odds (
    odds_id INT AUTO_INCREMENT PRIMARY KEY,
    game_id INT NOT NULL,
    odds_type ENUM('spread', 'moneyline', 'over_under') NOT NULL,
    side ENUM('home', 'away', 'over', 'under') NOT NULL,
    line_value DECIMAL(5,2), -- e.g., -1.5 for spread, 45.5 for O/U
    american_odds INT, -- e.g., -110, +150
    decimal_odds DECIMAL(6,3),
    implied_probability DECIMAL(5,4),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR(50) DEFAULT 'bovada',
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    INDEX idx_game_odds (game_id, odds_type)
);

-- Bets table
CREATE TABLE bets (
    bet_id INT AUTO_INCREMENT PRIMARY KEY,
    game_id INT NOT NULL,
    bet_type ENUM('spread', 'moneyline', 'over_under') NOT NULL,
    side ENUM('home', 'away', 'over', 'under') NOT NULL,
    bet_amount DECIMAL(10,2) NOT NULL,
    line_value DECIMAL(5,2),
    american_odds INT NOT NULL,
    decimal_odds DECIMAL(6,3),
    potential_return DECIMAL(10,2),
    actual_return DECIMAL(10,2),
    profit_loss DECIMAL(10,2),
    result ENUM('pending', 'win', 'loss', 'push', 'cancelled'),
    bet_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    strategy VARCHAR(100), -- e.g., 'kelly_criterion', 'value_bet'
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    INDEX idx_bet_date (bet_date),
    INDEX idx_result (result)
);

-- Team ratings table (sport-specific metrics like SRS, ELO, etc.)
CREATE TABLE team_ratings (
    rating_id INT AUTO_INCREMENT PRIMARY KEY,
    team_id INT NOT NULL,
    rating_date DATE NOT NULL,
    rating_type VARCHAR(50) NOT NULL, -- 'SRS', 'ELO', 'NET_RATING', etc.
    rating_value DECIMAL(10,4),
    rank INT,
    metadata JSON, -- For additional sport-specific stats
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    UNIQUE KEY unique_team_rating (team_id, rating_date, rating_type),
    INDEX idx_rating_date (rating_date)
);

-- Model predictions table
CREATE TABLE predictions (
    prediction_id INT AUTO_INCREMENT PRIMARY KEY,
    game_id INT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    predicted_spread DECIMAL(5,2),
    predicted_total DECIMAL(5,2),
    home_win_probability DECIMAL(5,4),
    away_win_probability DECIMAL(5,4),
    expected_value DECIMAL(10,4), -- EV for recommended bet
    recommended_bet_type ENUM('spread', 'moneyline', 'over_under'),
    recommended_side ENUM('home', 'away', 'over', 'under'),
    recommended_bet_amount DECIMAL(10,2),
    confidence_score DECIMAL(5,4),
    prediction_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    INDEX idx_prediction_date (prediction_date)
);

-- Bankroll tracking
CREATE TABLE bankroll_history (
    entry_id INT AUTO_INCREMENT PRIMARY KEY,
    entry_date DATE NOT NULL,
    sport_id INT,
    balance DECIMAL(10,2) NOT NULL,
    total_wagered DECIMAL(10,2),
    total_won DECIMAL(10,2),
    total_lost DECIMAL(10,2),
    roi DECIMAL(8,4),
    num_bets INT,
    win_rate DECIMAL(5,4),
    notes TEXT,
    FOREIGN KEY (sport_id) REFERENCES sports(sport_id),
    UNIQUE KEY unique_date_sport (entry_date, sport_id)
);

-- Insert initial sports
INSERT INTO sports (sport_name, sport_abbrev) VALUES
('Hockey', 'NHL'),
('NBA Basketball', 'NBA'),
('Football', 'NFL'),
('Baseball', 'MLB'),
('Men College Basketball', 'NCAAM'),
('Women College Basketball', 'NCAAW');
