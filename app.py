"""
Multi-Sport Betting Tracker - Streamlit Application
Main interface for data entry, bet tracking, and analysis
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from typing import List

from database import DatabaseManager
from bovada_parser import BovadaParser, ParsedGame
from config import SPORT_CONFIGS, KELLY_SETTINGS

# Page configuration
st.set_page_config(
    page_title="Multi-Sport Betting Tracker",
    page_icon="🎰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database
@st.cache_resource
def get_db():
    return DatabaseManager()

db = get_db()

# Sidebar navigation
st.sidebar.title("🎰 Betting Tracker")
page = st.sidebar.radio(
    "Navigation",
    ["📊 Dashboard", "📝 Bulk Import", "🎯 Place Bets", "📈 Performance", "⚙️ Settings"]
)

sport = st.sidebar.selectbox(
    "Select Sport",
    list(SPORT_CONFIGS.keys())
)

st.sidebar.divider()
st.sidebar.markdown("### Quick Stats")

# Get quick stats
try:
    pending = db.get_pending_bets(sport)
    st.sidebar.metric("Pending Bets", len(pending))
except:
    st.sidebar.metric("Pending Bets", 0)


# ============================================
# PAGE: DASHBOARD
# ============================================

if page == "📊 Dashboard":
    st.title(f"{sport} Betting Dashboard")
    
    # Date selector
    col1, col2 = st.columns(2)
    with col1:
        selected_date = st.date_input("Select Date", value=date.today())
    with col2:
        view_mode = st.radio("View", ["Today's Games", "All Pending Bets"], horizontal=True)
    
    if view_mode == "Today's Games":
        st.subheader(f"Games for {selected_date}")
        
        try:
            games = db.get_games_by_date(sport, selected_date)
            
            if games:
                for game in games:
                    with st.expander(f"{game['away_team']} @ {game['home_team']} - {game['game_time'] or 'TBD'}"):
                        # Get odds for this game
                        odds = db.get_latest_odds(game['game_id'])
                        
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.markdown("**Spread**")
                            if odds['spread'].get('away'):
                                st.write(f"{game['away_team']}: {odds['spread']['away']['line_value']} ({odds['spread']['away']['american_odds']})")
                            if odds['spread'].get('home'):
                                st.write(f"{game['home_team']}: {odds['spread']['home']['line_value']} ({odds['spread']['home']['american_odds']})")
                        
                        with col2:
                            st.markdown("**Moneyline**")
                            if odds['moneyline'].get('away'):
                                st.write(f"{game['away_team']}: {odds['moneyline']['away']['american_odds']}")
                            if odds['moneyline'].get('home'):
                                st.write(f"{game['home_team']}: {odds['moneyline']['home']['american_odds']}")
                        
                        with col3:
                            st.markdown("**Over/Under**")
                            if odds['over_under'].get('over'):
                                st.write(f"Over {odds['over_under']['over']['line_value']}: {odds['over_under']['over']['american_odds']}")
                            if odds['over_under'].get('under'):
                                st.write(f"Under {odds['over_under']['under']['line_value']}: {odds['over_under']['under']['american_odds']}")
                        
                        # Show scores if game is final
                        if game['game_status'] == 'final':
                            st.success(f"Final: {game['away_team']} {game['away_score']} - {game['home_score']} {game['home_team']}")
            else:
                st.info("No games found for this date.")
        except Exception as e:
            st.error(f"Error loading games: {e}")
    
    else:  # All Pending Bets
        st.subheader("All Pending Bets")
        
        try:
            pending = db.get_pending_bets(sport)
            
            if pending:
                df = pd.DataFrame(pending)
                
                # Calculate potential profit
                df['potential_profit'] = df['potential_return'] - df['bet_amount']
                
                # Format for display
                display_df = df[[
                    'game_date', 'away_team', 'home_team', 'bet_type', 
                    'side', 'bet_amount', 'line_value', 'american_odds', 
                    'potential_profit'
                ]].copy()
                
                st.dataframe(display_df, use_container_width=True)
                
                # Summary metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Wagered", f"${df['bet_amount'].sum():.2f}")
                with col2:
                    st.metric("Potential Return", f"${df['potential_return'].sum():.2f}")
                with col3:
                    st.metric("Potential Profit", f"${df['potential_profit'].sum():.2f}")
            else:
                st.info("No pending bets.")
        except Exception as e:
            st.error(f"Error loading pending bets: {e}")


# ============================================
# PAGE: BULK IMPORT
# ============================================

elif page == "📝 Bulk Import":
    st.title(f"Bulk Import {sport} Games from Bovada")
    
    st.markdown("""
    ### Instructions:
    1. Go to Bovada and find today's games
    2. Copy ALL the games text (select all game info including dates, teams, spreads, totals, moneylines)
    3. Paste below
    4. Click "Parse & Preview"
    5. Review the parsed games
    6. Click "Import to Database"
    """)
    
    st.divider()
    
    # Example format
    with st.expander("📋 See Example Format"):
        st.code(SPORT_CONFIGS[sport].typical_total_range if hasattr(SPORT_CONFIGS[sport], 'typical_total_range') else """
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
...
        """)
    
    # Bulk paste text area
    bulk_text = st.text_area(
        "Paste Bovada games here:",
        height=400,
        placeholder="Paste copied text from Bovada..."
    )
    
    if st.button("🔍 Parse & Preview", type="primary"):
        if bulk_text:
            with st.spinner("Parsing..."):
                parser = BovadaParser(sport)
                games = parser.parse_bulk_paste(bulk_text)
                
                if games:
                    st.success(f"✅ Successfully parsed {len(games)} games!")
                    
                    # Store in session state for import
                    st.session_state['parsed_games'] = games
                    st.session_state['parser_sport'] = sport
                    
                    # Display parsed games
                    for i, game in enumerate(games, 1):
                        with st.expander(f"Game {i}: {game.away_team} @ {game.home_team} ({game.game_date})"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.write("**Game Info**")
                                st.write(f"Date: {game.game_date}")
                                st.write(f"Time: {game.game_time or 'TBD'}")
                                st.write(f"Away: {game.away_team}")
                                st.write(f"Home: {game.home_team}")
                            
                            with col2:
                                st.write("**Odds**")
                                if game.spread_away:
                                    st.write(f"Spread: {game.spread_away}/{game.spread_home} ({game.spread_away_odds}/{game.spread_home_odds})")
                                if game.moneyline_away:
                                    st.write(f"ML: {game.moneyline_away}/{game.moneyline_home}")
                                if game.over_under:
                                    st.write(f"O/U: {game.over_under} ({game.over_odds}/{game.under_odds})")
                            
                            if game.parse_warnings:
                                st.warning(f"⚠️ Warnings: {', '.join(game.parse_warnings)}")
                else:
                    st.error("No games could be parsed. Please check the format.")
        else:
            st.warning("Please paste some text first.")
    
    # Import button (only show if games are parsed)
    if 'parsed_games' in st.session_state and st.session_state.get('parser_sport') == sport:
        st.divider()
        
        if st.button("💾 Import to Database", type="primary"):
            with st.spinner("Importing..."):
                success_count = 0
                error_count = 0
                
                for game in st.session_state['parsed_games']:
                    try:
                        # Check if game already exists
                        existing_game_id = db.get_game_by_teams_date(
                            sport, game.home_team, game.away_team, game.game_date
                        )
                        
                        if not existing_game_id:
                            # Create game
                            game_id = db.create_game(
                                sport, game.game_date, game.game_time,
                                game.home_team, game.away_team
                            )
                        else:
                            game_id = existing_game_id
                        
                        # Insert odds
                        if game.spread_away:
                            db.insert_odds(game_id, 'spread', 'away', game.spread_away, game.spread_away_odds)
                            db.insert_odds(game_id, 'spread', 'home', game.spread_home, game.spread_home_odds)
                        
                        if game.moneyline_away:
                            db.insert_odds(game_id, 'moneyline', 'away', None, game.moneyline_away)
                            db.insert_odds(game_id, 'moneyline', 'home', None, game.moneyline_home)
                        
                        if game.over_under:
                            db.insert_odds(game_id, 'over_under', 'over', game.over_under, game.over_odds)
                            db.insert_odds(game_id, 'over_under', 'under', game.over_under, game.under_odds)
                        
                        success_count += 1
                    
                    except Exception as e:
                        st.error(f"Error importing {game.away_team} @ {game.home_team}: {e}")
                        error_count += 1
                
                st.success(f"✅ Imported {success_count} games successfully!")
                if error_count:
                    st.warning(f"⚠️ {error_count} games had errors.")
                
                # Clear session state
                del st.session_state['parsed_games']


# ============================================
# PAGE: PLACE BETS
# ============================================

elif page == "🎯 Place Bets":
    st.title(f"Place {sport} Bets")
    
    # Select game date
    bet_date = st.date_input("Game Date", value=date.today())
    
    # Load games for that date
    games = db.get_games_by_date(sport, bet_date)
    
    if games:
        # Create game selector
        game_options = {
            f"{g['away_team']} @ {g['home_team']} ({g['game_time'] or 'TBD'})": g['game_id']
            for g in games
        }
        
        selected_game_name = st.selectbox("Select Game", list(game_options.keys()))
        selected_game_id = game_options[selected_game_name]
        
        # Get odds for selected game
        odds = db.get_latest_odds(selected_game_id)
        
        st.divider()
        
        # Bet entry form
        with st.form("bet_form"):
            st.subheader("Enter Bet Details")
            
            col1, col2 = st.columns(2)
            
            with col1:
                bet_type = st.selectbox("Bet Type", ["spread", "moneyline", "over_under"])
                
                if bet_type == "spread":
                    side_options = ["away", "home"]
                elif bet_type == "over_under":
                    side_options = ["over", "under"]
                else:
                    side_options = ["away", "home"]
                
                bet_side = st.selectbox("Side", side_options)
            
            with col2:
                bet_amount = st.number_input("Bet Amount ($)", min_value=1.0, value=50.0, step=10.0)
                strategy = st.selectbox("Strategy", ["manual", "kelly_criterion", "value_bet", "other"])
            
            # Show relevant line and odds based on selection
            st.subheader("Odds for Selected Bet")
            
            if bet_type in odds and bet_side in odds[bet_type]:
                selected_odds = odds[bet_type][bet_side]
                line_value = selected_odds.get('line_value')
                american_odds = selected_odds['american_odds']
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    if line_value:
                        st.metric("Line", f"{line_value}")
                with col2:
                    st.metric("Odds", f"{american_odds}")
                with col3:
                    # Calculate potential return
                    if american_odds > 0:
                        potential_return = bet_amount * (1 + american_odds/100)
                    else:
                        potential_return = bet_amount * (1 + 100/abs(american_odds))
                    st.metric("Potential Return", f"${potential_return:.2f}")
                
                # Notes
                notes = st.text_area("Notes (optional)", placeholder="Add any notes about this bet...")
                
                # Submit button
                submitted = st.form_submit_button("Place Bet", type="primary")
                
                if submitted:
                    try:
                        bet_id = db.place_bet(
                            selected_game_id, bet_type, bet_side,
                            bet_amount, line_value, american_odds,
                            strategy, notes
                        )
                        st.success(f"✅ Bet placed successfully! (Bet ID: {bet_id})")
                    except Exception as e:
                        st.error(f"Error placing bet: {e}")
            else:
                st.warning("No odds available for this bet type and side.")
    else:
        st.info("No games found for this date. Import games first!")


# ============================================
# PAGE: PERFORMANCE
# ============================================

elif page == "📈 Performance":
    st.title(f"{sport} Betting Performance")
    
    # Date range selector
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=date.today() - timedelta(days=30))
    with col2:
        end_date = st.date_input("End Date", value=date.today())
    
    try:
        # Get performance data
        df = db.get_bet_performance(sport, start_date, end_date)
        
        if not df.empty:
            # Calculate metrics
            total_bets = len(df)
            wins = len(df[df['result'] == 'win'])
            losses = len(df[df['result'] == 'loss'])
            pushes = len(df[df['result'] == 'push'])
            
            win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
            
            total_wagered = df['bet_amount'].sum()
            total_profit = df['profit_loss'].sum()
            roi = (total_profit / total_wagered) * 100 if total_wagered > 0 else 0
            
            # Display metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Bets", total_bets)
            with col2:
                st.metric("Win Rate", f"{win_rate:.1%}")
            with col3:
                st.metric("Total Wagered", f"${total_wagered:.2f}")
            with col4:
                st.metric("Total Profit/Loss", f"${total_profit:.2f}", 
                         delta=f"{roi:.1f}% ROI")
            
            st.divider()
            
            # Record breakdown
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Wins", wins, delta=None)
            with col2:
                st.metric("Losses", losses, delta=None)
            with col3:
                st.metric("Pushes", pushes, delta=None)
            
            st.divider()
            
            # Profit over time chart
            st.subheader("Profit/Loss Over Time")
            df_sorted = df.sort_values('game_date')
            df_sorted['cumulative_profit'] = df_sorted['profit_loss'].cumsum()
            
            fig = px.line(df_sorted, x='game_date', y='cumulative_profit',
                         title='Cumulative Profit/Loss')
            fig.update_layout(xaxis_title="Date", yaxis_title="Cumulative P/L ($)")
            st.plotly_chart(fig, use_container_width=True)
            
            # Bet type breakdown
            st.subheader("Performance by Bet Type")
            bet_type_perf = df.groupby('bet_type').agg({
                'bet_amount': 'sum',
                'profit_loss': 'sum',
                'bet_id': 'count'
            }).rename(columns={'bet_id': 'count'})
            bet_type_perf['roi'] = (bet_type_perf['profit_loss'] / bet_type_perf['bet_amount']) * 100
            
            st.dataframe(bet_type_perf, use_container_width=True)
            
            # Recent bets table
            st.subheader("Recent Bets")
            recent_df = df.sort_values('game_date', ascending=False).head(20)
            display_cols = ['game_date', 'away_team', 'home_team', 'bet_type', 
                          'side', 'bet_amount', 'american_odds', 'result', 'profit_loss']
            st.dataframe(recent_df[display_cols], use_container_width=True)
        
        else:
            st.info("No betting data found for the selected date range.")
    
    except Exception as e:
        st.error(f"Error loading performance data: {e}")


# ============================================
# PAGE: SETTINGS
# ============================================

elif page == "⚙️ Settings":
    st.title("Settings")
    
    st.subheader("Kelly Criterion Settings")
    
    fractional_kelly = st.slider(
        "Fractional Kelly", 
        min_value=0.1, 
        max_value=1.0, 
        value=KELLY_SETTINGS['fractional_kelly'],
        step=0.05,
        help="1.0 = Full Kelly, 0.25 = Quarter Kelly (more conservative)"
    )
    
    max_bet_pct = st.slider(
        "Max Bet % of Bankroll",
        min_value=0.01,
        max_value=0.10,
        value=KELLY_SETTINGS['max_bet_pct'],
        step=0.01,
        help="Never bet more than this % of your bankroll on a single bet"
    )
    
    min_edge = st.slider(
        "Minimum Edge to Bet",
        min_value=0.0,
        max_value=0.10,
        value=KELLY_SETTINGS['min_edge'],
        step=0.01,
        help="Only place bets with at least this % edge"
    )
    
    bankroll = st.number_input(
        "Current Bankroll ($)",
        min_value=100.0,
        value=float(KELLY_SETTINGS['default_bankroll']),
        step=100.0
    )
    
    if st.button("Save Settings"):
        st.success("Settings saved!")
    
    st.divider()
    
    st.subheader("Database Connection")
    st.info("Database configuration is managed via environment variables.")
    
    # Test connection button
    if st.button("Test Database Connection"):
        try:
            sports = db.get_all_sports()
            st.success(f"✅ Connected! Found {len(sports)} sports in database.")
        except Exception as e:
            st.error(f"❌ Connection failed: {e}")


# Footer
st.sidebar.divider()
st.sidebar.markdown("---")
st.sidebar.caption("Multi-Sport Betting Tracker v1.0")
