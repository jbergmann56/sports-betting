# 🎰 Multi-Sport Betting Tracker

A comprehensive, extensible betting tracker application with automated data collection, bulk import capabilities, and advanced analytics. Built for serious sports bettors who want to track performance across multiple sports.

## 🌟 Features

### ✅ Currently Supported
- **Multi-Sport Support**: NHL, NBA, NFL, MLB, NCAA Basketball (easily extensible)
- **Bulk Import**: Copy/paste games directly from Bovada - no manual entry
- **Bet Tracking**: Track spreads, moneylines, and over/unders
- **Performance Analytics**: Win rates, ROI, profit/loss tracking
- **Historical Data Import**: Import your existing Excel betting data
- **Kelly Criterion Calculator**: Optimize bet sizing
- **Azure MySQL Backend**: Scalable cloud database storage
- **Streamlit UI**: Clean, intuitive web interface

### 🚧 Coming Soon
- Automated odds scraping from multiple sportsbooks
- Live score updates via APIs
- Advanced model predictions
- Email/SMS alerts for +EV bets
- Mobile-responsive improvements

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│         Streamlit Frontend              │
│   (Bet entry, bulk import, analytics)   │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│      Python Application Layer           │
│  • Database Manager                     │
│  • Bovada Parser                        │
│  • Historical Importer                  │
│  • Sport-specific modules               │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│         Azure MySQL Database            │
│  • Games & Teams                        │
│  • Odds & Lines                         │
│  • Bets & Results                       │
│  • Team Ratings (SRS, etc.)             │
└─────────────────────────────────────────┘
```

## 📋 Prerequisites

- Python 3.8+
- Azure MySQL Database (or local MySQL)
- Azure Data Lake Gen2 (optional, for future features)

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone <your-repo>
cd betting-tracker
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the `.env.template` to `.env` and fill in your Azure MySQL credentials:

```bash
cp .env.template .env
nano .env  # Edit with your credentials
```

**Required variables:**
```
AZURE_MYSQL_HOST=your-server.mysql.database.azure.com
AZURE_MYSQL_USER=your_username@your-server
AZURE_MYSQL_PASSWORD=your_password
AZURE_MYSQL_DATABASE=betting_tracker
AZURE_MYSQL_PORT=3306
```

### 4. Run Setup

This will create database tables and optionally import historical data:

```bash
python setup.py
```

### 5. Start the Application

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## 📊 Using the Application

### Bulk Import from Bovada

1. Navigate to **📝 Bulk Import**
2. Go to Bovada and find today's games
3. Select and copy ALL game information (dates, teams, odds)
4. Paste into the text area
5. Click **Parse & Preview**
6. Review parsed games and click **Import to Database**

**Example format:**
```
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
```

### Placing Bets

1. Navigate to **🎯 Place Bets**
2. Select the game date and game
3. Choose bet type (spread/moneyline/over-under)
4. Enter bet amount
5. Review odds and potential return
6. Click **Place Bet**

### Viewing Performance

1. Navigate to **📈 Performance**
2. Select date range
3. View metrics:
   - Win rate
   - Total profit/loss
   - ROI
   - Performance by bet type
   - Cumulative profit chart

## 🗄️ Database Schema

### Core Tables

**`sports`**: Available sports (NHL, NBA, NFL, etc.)  
**`teams`**: All teams across all sports  
**`games`**: Individual games with dates and teams  
**`odds`**: Historical odds for each game  
**`bets`**: Your placed bets with outcomes  
**`team_ratings`**: Team performance metrics (SRS, ELO, etc.)  
**`predictions`**: Model predictions (future feature)  

See `schema.sql` for complete schema.

## 🔧 Adding a New Sport

The system is designed to be easily extensible. To add a new sport:

### 1. Update `config.py`

```python
SPORT_CONFIGS['YOUR_SPORT'] = SportConfig(
    name='Your Sport',
    abbrev='YOUR_SPORT',
    stat_source='https://...',
    primary_rating='RATING_TYPE',
    typical_total_range=(min, max)
)
```

### 2. Add Team Name Mappings

```python
TEAM_NAME_MAPPINGS['YOUR_SPORT'] = {
    'Abbrev': 'Full Team Name',
    # ...
}
```

### 3. Create Sport-Specific Module (Optional)

For sport-specific logic:
```python
# sports/your_sport.py
class YourSportHandler:
    def calculate_spread(self, ...):
        # Sport-specific calculations
        pass
```

### 4. Add to Database

```sql
INSERT INTO sports (sport_name, sport_abbrev) 
VALUES ('Your Sport', 'YOUR_SPORT');
```

## 📦 Project Structure

```
betting-tracker/
├── app.py                    # Main Streamlit application
├── config.py                 # Configuration and constants
├── database.py               # Database manager
├── bovada_parser.py          # Bulk paste parser
├── historical_importer.py    # Excel data importer
├── schema.sql                # Database schema
├── requirements.txt          # Python dependencies
├── setup.py                  # Setup script
├── .env.template             # Environment template
└── README.md                 # This file
```

## 🔐 Security Notes

- **Never commit `.env` file** - It contains credentials
- Use Azure Key Vault for production deployments
- Enable SSL for MySQL connections
- Rotate database passwords regularly

## 🚀 Deployment Options

### Option 1: Local Machine
Run on your laptop/desktop for personal use:
```bash
streamlit run app.py
```

### Option 2: Azure App Service
Deploy to Azure for cloud access:

1. Create Azure App Service (Python 3.8+)
2. Set environment variables in Application Settings
3. Deploy via Git or Azure CLI
4. Configure custom domain (optional)

### Option 3: Docker
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["streamlit", "run", "app.py"]
```

## 📊 Integration with Tableau

The MySQL database can be connected directly to Tableau:

1. In Tableau, select **MySQL** connector
2. Enter your Azure MySQL credentials
3. Select tables to import
4. Create visualizations

**Recommended approach:**
- Use Streamlit for daily operations (bet entry, quick views)
- Use Tableau for deep analysis and presentations

## 🤝 Contributing

This is a personal project, but suggestions are welcome!

Areas for improvement:
- Additional sportsbooks beyond Bovada
- Machine learning models for predictions
- Mobile app version
- Live odds tracking
- Arbitrage opportunity detection

## 📝 Future Roadmap

### Phase 1 (Current) ✅
- Multi-sport support
- Bulk import from Bovada
- Basic bet tracking
- Historical data import

### Phase 2 (Next)
- [ ] Automated odds scraping
- [ ] NHL API integration for live scores
- [ ] Kelly Criterion automation
- [ ] Alert system for +EV bets

### Phase 3 (Future)
- [ ] Machine learning models
- [ ] Multiple sportsbook comparison
- [ ] Arbitrage detection
- [ ] Social features (share picks)

## 🐛 Troubleshooting

### Database Connection Issues
```bash
# Test connection
python -c "from database import DatabaseManager; db = DatabaseManager(); print('Connected!' if db else 'Failed')"
```

### Import Errors
- Check that Excel file is in correct format
- Verify team names match database
- Check date formats (MM/DD/YYYY)

### Streamlit Won't Start
```bash
# Check port availability
lsof -i :8501

# Run on different port
streamlit run app.py --server.port 8502
```

## 📧 Support

For issues or questions:
1. Check the troubleshooting section
2. Review error logs in terminal
3. Verify database connection and credentials

## 📄 License

This is a personal project. Use at your own risk. Sports betting involves financial risk.

**Disclaimer**: This tool is for tracking and analysis purposes only. Always gamble responsibly.

---

Built with ❤️ by a data-driven sports bettor
