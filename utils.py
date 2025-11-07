"""
Utility Functions for Betting Tracker
Common calculations and helper functions
"""

import numpy as np
from typing import Tuple, Optional


def american_to_decimal(american_odds: int) -> float:
    """Convert American odds to decimal odds"""
    if american_odds > 0:
        return (american_odds / 100) + 1
    else:
        return (100 / abs(american_odds)) + 1


def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds"""
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def calculate_implied_probability(american_odds: int) -> float:
    """Calculate implied probability from American odds"""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


def remove_vig(prob_a: float, prob_b: float) -> Tuple[float, float]:
    """
    Remove vigorish (bookmaker's edge) from probabilities
    Returns fair probabilities for both sides
    """
    total = prob_a + prob_b
    vig = total - 1.0
    
    fair_prob_a = prob_a / total
    fair_prob_b = prob_b / total
    
    return fair_prob_a, fair_prob_b


def calculate_kelly_criterion(win_probability: float, 
                              decimal_odds: float,
                              fractional_kelly: float = 0.25) -> float:
    """
    Calculate optimal bet size using Kelly Criterion
    
    Args:
        win_probability: Your estimated probability of winning (0-1)
        decimal_odds: Decimal odds offered by bookmaker
        fractional_kelly: Fraction of Kelly to use (0.25 = quarter Kelly)
    
    Returns:
        Fraction of bankroll to bet (0-1)
    """
    # Kelly formula: (bp - q) / b
    # where b = decimal_odds - 1, p = win probability, q = lose probability
    b = decimal_odds - 1
    q = 1 - win_probability
    
    kelly = (b * win_probability - q) / b
    
    # Apply fractional Kelly for safety
    kelly *= fractional_kelly
    
    # Never bet negative amounts
    return max(0, kelly)


def calculate_ev(win_probability: float, 
                decimal_odds: float, 
                bet_amount: float = 1.0) -> float:
    """
    Calculate expected value of a bet
    
    Returns:
        Expected profit (positive) or loss (negative)
    """
    win_amount = bet_amount * (decimal_odds - 1)
    lose_amount = -bet_amount
    
    ev = (win_probability * win_amount) + ((1 - win_probability) * lose_amount)
    
    return ev


def calculate_required_win_rate(american_odds: int) -> float:
    """
    Calculate the win rate needed to break even at given odds
    """
    return calculate_implied_probability(american_odds)


def calculate_roi(bets_df) -> dict:
    """
    Calculate ROI metrics from a DataFrame of bets
    
    Args:
        bets_df: DataFrame with columns 'bet_amount', 'profit_loss', 'result'
    
    Returns:
        Dictionary with ROI metrics
    """
    if len(bets_df) == 0:
        return {
            'total_bets': 0,
            'total_wagered': 0,
            'total_profit': 0,
            'roi': 0,
            'win_rate': 0
        }
    
    total_bets = len(bets_df)
    total_wagered = bets_df['bet_amount'].sum()
    total_profit = bets_df['profit_loss'].sum()
    roi = (total_profit / total_wagered) * 100 if total_wagered > 0 else 0
    
    # Calculate win rate (excluding pushes)
    completed = bets_df[bets_df['result'].isin(['win', 'loss'])]
    wins = len(completed[completed['result'] == 'win'])
    win_rate = wins / len(completed) if len(completed) > 0 else 0
    
    return {
        'total_bets': total_bets,
        'total_wagered': total_wagered,
        'total_profit': total_profit,
        'roi': roi,
        'win_rate': win_rate
    }


def calculate_sharpe_ratio(returns: list, risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sharpe ratio for betting performance
    
    Args:
        returns: List of returns (profit/loss as fraction of bet)
        risk_free_rate: Risk-free rate (typically 0 for sports betting)
    
    Returns:
        Sharpe ratio
    """
    if len(returns) < 2:
        return 0.0
    
    returns_array = np.array(returns)
    excess_returns = returns_array - risk_free_rate
    
    return np.mean(excess_returns) / np.std(excess_returns) if np.std(excess_returns) > 0 else 0.0


def estimate_true_probability(model_prob: float, 
                              market_prob: float,
                              model_weight: float = 0.7) -> float:
    """
    Blend model probability with market probability
    
    Args:
        model_prob: Your model's estimated probability
        market_prob: Market implied probability
        model_weight: Weight to give to model (0-1)
    
    Returns:
        Blended probability
    """
    return (model_weight * model_prob) + ((1 - model_weight) * market_prob)


def calculate_units_won(profit_loss: float, unit_size: float = 100.0) -> float:
    """
    Convert dollar P/L to units won
    
    Args:
        profit_loss: Profit or loss in dollars
        unit_size: Size of one unit in dollars
    
    Returns:
        Units won (positive) or lost (negative)
    """
    return profit_loss / unit_size


def parlay_odds(*american_odds_list) -> int:
    """
    Calculate combined American odds for a parlay
    
    Args:
        *american_odds_list: Variable number of American odds
    
    Returns:
        Combined American odds for the parlay
    """
    decimal_odds = [american_to_decimal(odds) for odds in american_odds_list]
    combined_decimal = np.prod(decimal_odds)
    return decimal_to_american(combined_decimal)


def calculate_breakeven_point(fixed_costs: float, 
                              unit_size: float = 100.0,
                              win_rate: float = 0.53,
                              avg_odds: int = -110) -> int:
    """
    Calculate number of bets needed to break even given fixed costs
    (e.g., data subscriptions, tools)
    
    Args:
        fixed_costs: Monthly fixed costs in dollars
        unit_size: Standard bet size
        win_rate: Expected win rate
        avg_odds: Average odds you're betting at
    
    Returns:
        Number of bets needed to break even
    """
    decimal_odds = american_to_decimal(avg_odds)
    expected_profit_per_bet = (win_rate * unit_size * (decimal_odds - 1)) - ((1 - win_rate) * unit_size)
    
    if expected_profit_per_bet <= 0:
        return float('inf')  # Can't break even with negative expectation
    
    return int(np.ceil(fixed_costs / expected_profit_per_bet))


def format_odds(american_odds: int) -> str:
    """Format odds with + or - prefix"""
    return f"{american_odds:+d}"


def format_currency(amount: float) -> str:
    """Format amount as currency"""
    return f"${amount:,.2f}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format decimal as percentage"""
    return f"{value * 100:.{decimals}f}%"


# Example usage and tests
if __name__ == "__main__":
    print("=== Betting Math Utilities ===\n")
    
    # Test odds conversion
    print("Odds Conversion:")
    print(f"  American -110 → Decimal {american_to_decimal(-110):.3f}")
    print(f"  American +150 → Decimal {american_to_decimal(150):.3f}")
    print(f"  Decimal 1.909 → American {decimal_to_american(1.909)}")
    print()
    
    # Test Kelly Criterion
    print("Kelly Criterion (55% win rate, -110 odds, 1/4 Kelly):")
    decimal_odds = american_to_decimal(-110)
    kelly = calculate_kelly_criterion(0.55, decimal_odds, 0.25)
    print(f"  Recommended bet: {kelly:.2%} of bankroll")
    print(f"  For $3000 bankroll: ${3000 * kelly:.2f}")
    print()
    
    # Test EV calculation
    print("Expected Value (55% win rate, -110 odds, $100 bet):")
    ev = calculate_ev(0.55, decimal_odds, 100)
    print(f"  EV: ${ev:.2f}")
    print()
    
    # Test parlay calculation
    print("Parlay Odds (-110, -110, -110):")
    parlay = parlay_odds(-110, -110, -110)
    print(f"  Combined odds: {format_odds(parlay)}")
    print(f"  $100 bet pays: ${100 * american_to_decimal(parlay):.2f}")
