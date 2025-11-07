# Quick Reference Guide

## 🚀 Common Commands

### Starting the Application
```bash
# Start Streamlit app
streamlit run app.py

# Start on different port
streamlit run app.py --server.port 8502

# Run in background (Linux/Mac)
nohup streamlit run app.py &
```

### Database Operations
```bash
# Test database connection
python -c "from database import DatabaseManager; db = DatabaseManager(); print('✅ Connected!')"

# Run setup/initialization
python setup.py

# Import historical data
python historical_importer.py
```

### Testing
```bash
# Test parser
python demo.py

# Test utilities
python utils.py
```

## 📝 Daily Workflow

### Morning (2 minutes)
1. Open Bovada
2. Find tonight's games
3. Select all text and copy (Ctrl+C / Cmd+C)
4. Open app → Bulk Import page
5. Paste (Ctrl+V / Cmd+V)
6. Click "Parse & Preview"
7. Review → Click "Import to Database"

### Afternoon (5 minutes)
1. Open app → Place Bets page
2. Select game from dropdown
3. Choose bet type and side
4. Enter amount (Kelly calculated automatically)
5. Click "Place Bet"
6. Repeat for other games

### Night (0 minutes)
- Watch games, system tracks everything!

### Next Morning (2 minutes)
1. Open app → Dashboard
2. View yesterday's results
3. System auto-calculates P&L

## 🎯 Keyboard Shortcuts (Streamlit)

- `r` - Rerun app
- `c` - Clear cache
- `Ctrl+S` - Save (text editors)
- `Ctrl+Enter` - Submit form

## 🔧 Environment Variables

Required in `.env` file:
```bash
AZURE_MYSQL_HOST=your-server.mysql.database.azure.com
AZURE_MYSQL_USER=your_username@your-server
AZURE_MYSQL_PASSWORD=your_password
AZURE_MYSQL_DATABASE=betting_tracker
AZURE_MYSQL_PORT=3306
```

## 📊 Common Database Queries

### Check recent games
```sql
SELECT g.game_date, t1.team_name as away, t2.team_name as home, 
       g.away_score, g.home_score
FROM games g
JOIN teams t1 ON g.away_team_id = t1.team_id
JOIN teams t2 ON g.home_team_id = t2.team_id
WHERE g.game_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY g.game_date DESC;
```

### Check bet performance
```sql
SELECT 
    COUNT(*) as total_bets,
    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
    SUM(bet_amount) as total_wagered,
    SUM(profit_loss) as total_profit,
    (SUM(profit_loss) / SUM(bet_amount)) * 100 as roi
FROM bets
WHERE result != 'pending';
```

### Find profitable bet types
```sql
SELECT 
    bet_type,
    COUNT(*) as bets,
    SUM(profit_loss) as profit,
    AVG(profit_loss) as avg_profit
FROM bets
WHERE result != 'pending'
GROUP BY bet_type
ORDER BY profit DESC;
```

## 🛠️ Troubleshooting Quick Fixes

### "Module not found" error
```bash
pip install -r requirements.txt
```

### "Can't connect to database"
```bash
# Check .env file exists
ls -la .env

# Verify credentials
cat .env

# Test connection
python -c "from database import DatabaseManager; DatabaseManager()"
```

### "Streamlit won't start"
```bash
# Check if port is in use
lsof -i :8501

# Kill process if needed
kill -9 <PID>

# Or use different port
streamlit run app.py --server.port 8502
```

### Parser not working
```bash
# Test with demo data
python demo.py

# Check team name mappings in config.py
```

### Import errors
- Verify Excel file path
- Check sheet names match
- Ensure date columns are formatted correctly

## 📈 Performance Tips

### Speed up bulk imports
- Import during off-hours
- Process 50-100 games at once
- Database indexes auto-handle speed

### Optimize Streamlit
- Use `@st.cache_data` for expensive functions
- Minimize database calls in loops
- Use `st.dataframe()` instead of `st.table()` for large data

### Database optimization
```sql
-- Add indexes if queries slow
CREATE INDEX idx_game_date ON games(game_date);
CREATE INDEX idx_team_name ON teams(team_name);
```

## 🎨 Customization Examples

### Change Kelly fraction
Edit `config.py`:
```python
KELLY_SETTINGS = {
    'fractional_kelly': 0.5,  # Use half Kelly instead of quarter
    ...
}
```

### Add team abbreviation
Edit `config.py`:
```python
TEAM_NAME_MAPPINGS['NHL']['EDM'] = 'Edmonton Oilers'
```

### Custom bet strategy
In `app.py`, add to strategy dropdown:
```python
strategy = st.selectbox("Strategy", [
    "manual", 
    "kelly_criterion", 
    "value_bet", 
    "my_custom_strategy"  # Add your own
])
```

## 💾 Backup and Restore

### Backup database
```bash
# Export all data
mysqldump -h $AZURE_MYSQL_HOST -u $AZURE_MYSQL_USER -p \
    $AZURE_MYSQL_DATABASE > backup_$(date +%Y%m%d).sql
```

### Restore database
```bash
# Import backup
mysql -h $AZURE_MYSQL_HOST -u $AZURE_MYSQL_USER -p \
    $AZURE_MYSQL_DATABASE < backup_20241208.sql
```

## 🔐 Security Best Practices

1. Never commit `.env` file
2. Use strong database passwords
3. Enable SSL for MySQL connections
4. Rotate credentials quarterly
5. Use Azure Key Vault for production

## 📱 Access from Multiple Devices

### Option 1: Deploy to Azure
```bash
az webapp create --resource-group myResourceGroup \
    --plan myAppServicePlan --name mybettingapp \
    --runtime "PYTHON|3.9"
```

### Option 2: Use Ngrok (development)
```bash
# Install ngrok
brew install ngrok  # or download from ngrok.com

# Start app
streamlit run app.py

# In another terminal
ngrok http 8501

# Access from anywhere using ngrok URL
```

### Option 3: VPN
- Connect to home network via VPN
- Access via local IP: http://192.168.1.X:8501

## 📞 Need Help?

1. Check `README.md` for detailed docs
2. Check `PROJECT_SUMMARY.md` for architecture
3. Run `python demo.py` to test components
4. Review error messages carefully
5. Check database connection first

## 🎯 Success Checklist

- [ ] Installed all dependencies
- [ ] Created and configured `.env` file
- [ ] Ran `python setup.py` successfully
- [ ] Tested parser with `python demo.py`
- [ ] Started Streamlit with `streamlit run app.py`
- [ ] Imported first batch of games
- [ ] Placed first bet in system
- [ ] Reviewed performance dashboard

---

**Pro Tip**: Keep this file handy! Bookmark it or print it for quick reference.
