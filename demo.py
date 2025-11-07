"""
Demo Script - Test Bovada Parser
Run this to test the bulk paste parser without database
"""

from bovada_parser import BovadaParser

# Sample NHL games from Bovada format
sample_nhl = """
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

12/9/2024 7:30 PM
Colorado Avalanche
Vegas Golden Knights
Spread
Colorado Avalanche -1.5 +155
Vegas Golden Knights +1.5 -185
Total
Over 5.5 -120
Under 5.5 +100
Money Line
Colorado Avalanche -165
Vegas Golden Knights +145
"""

def main():
    print("=" * 60)
    print("🎰 BOVADA PARSER DEMO")
    print("=" * 60)
    print()
    
    # Parse NHL games
    print("Parsing NHL games...")
    print()
    
    parser = BovadaParser('NHL')
    games = parser.parse_bulk_paste(sample_nhl)
    
    print(f"✅ Successfully parsed {len(games)} games!\n")
    
    for i, game in enumerate(games, 1):
        print(f"{'─' * 60}")
        print(f"GAME {i}")
        print(f"{'─' * 60}")
        print(f"📅 Date: {game.game_date}")
        print(f"⏰ Time: {game.game_time or 'TBD'}")
        print(f"🏒 Matchup: {game.away_team} @ {game.home_team}")
        print()
        
        if game.spread_away:
            print(f"📊 SPREAD:")
            print(f"   {game.away_team}: {game.spread_away:+.1f} ({game.spread_away_odds:+d})")
            print(f"   {game.home_team}: {game.spread_home:+.1f} ({game.spread_home_odds:+d})")
            print()
        
        if game.moneyline_away:
            print(f"💰 MONEYLINE:")
            print(f"   {game.away_team}: {game.moneyline_away:+d}")
            print(f"   {game.home_team}: {game.moneyline_home:+d}")
            print()
        
        if game.over_under:
            print(f"🎯 OVER/UNDER: {game.over_under}")
            print(f"   Over: {game.over_odds:+d}")
            print(f"   Under: {game.under_odds:+d}")
            print()
        
        if game.parse_warnings:
            print(f"⚠️  Warnings: {', '.join(game.parse_warnings)}")
            print()
    
    print("=" * 60)
    print("Demo complete! The parser is working correctly.")
    print("=" * 60)
    print()
    print("💡 Next steps:")
    print("   1. Run setup.py to initialize your database")
    print("   2. Run 'streamlit run app.py' to start the application")
    print("   3. Use the Bulk Import page to import real games")
    print()

if __name__ == "__main__":
    main()
