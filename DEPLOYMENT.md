# Deploying to Streamlit Community Cloud

## Prerequisites

1. **GitHub Account** - Your code is already on GitHub ✅
2. **Streamlit Account** - Sign up at [share.streamlit.io](https://share.streamlit.io)
3. **Azure MySQL Database** - Your database must be accessible from the internet

## Step-by-Step Deployment Guide

### 1. Prepare Your Database

Ensure your Azure MySQL database allows connections from Streamlit Cloud:

```bash
# In Azure Portal:
# 1. Go to your MySQL server
# 2. Navigate to "Connection security"
# 3. Add firewall rule:
#    - Rule name: "Streamlit Cloud"
#    - Start IP: 0.0.0.0
#    - End IP: 255.255.255.255
#
# OR use "Allow access to Azure services" toggle
#
# ⚠️ WARNING: This opens your database to the internet
# Consider using Azure Private Link or VPN for production
```

### 2. Push Your Code to GitHub

```bash
# Make sure all files are committed
git status

# Add new files
git add .streamlit/config.toml
git add .gitignore
git add DEPLOYMENT.md

# Commit
git commit -m "Add Streamlit deployment configuration"

# Push to GitHub
git push origin main
```

### 3. Deploy on Streamlit Cloud

1. **Go to [share.streamlit.io](https://share.streamlit.io)**
2. **Sign in with GitHub**
3. **Click "New app"**
4. **Configure your app:**
   - **Repository:** `jbergmann56/app`
   - **Branch:** `main`
   - **Main file path:** `app.py`
5. **Click "Advanced settings"**
6. **Add your secrets:**
   ```toml
   AZURE_MYSQL_HOST = "your-server.mysql.database.azure.com"
   AZURE_MYSQL_USER = "your-username"
   AZURE_MYSQL_PASSWORD = "your-password"
   AZURE_MYSQL_DATABASE = "betting_tracker"
   AZURE_MYSQL_PORT = "3306"
   ```
7. **Click "Deploy!"**

### 4. Access Your App

Your app will be available at:
```
https://jbergmann56-app-app-[random].streamlit.app
```

The deployment takes 2-5 minutes. Streamlit will show logs during deployment.

## Configuration on Streamlit Cloud

Your app automatically reads from Streamlit secrets instead of `.env`:

```python
# config.py already handles both .env and Streamlit secrets
DB_CONFIG = {
    'host': os.getenv('AZURE_MYSQL_HOST') or st.secrets.get('AZURE_MYSQL_HOST'),
    # ... etc
}
```

**Update needed:** You need to modify `config.py` to support Streamlit secrets.

## Troubleshooting

### Database Connection Errors

**Error:** `Can't connect to MySQL server`

**Solutions:**
1. Check Azure firewall rules allow Streamlit's IPs
2. Verify credentials in Streamlit secrets
3. Ensure database is running
4. Test connection with MySQL Workbench

### Import Errors

**Error:** `ModuleNotFoundError`

**Solution:** Check all dependencies are in `requirements.txt`

### Memory Errors

**Free tier limits:**
- 1 GB RAM
- 1 CPU core

**Solutions:**
1. Optimize queries (use LIMIT)
2. Cache expensive operations with `@st.cache_data`
3. Upgrade to paid tier if needed

## Custom Domain (Optional)

Streamlit Cloud supports custom domains:

1. Go to app settings
2. Add custom domain: `betting.yourdomain.com`
3. Add CNAME record in your DNS:
   ```
   betting.yourdomain.com → your-app.streamlit.app
   ```

## Security Considerations

### ⚠️ IMPORTANT: This is a PRIVATE app

Your betting data is personal financial information. Consider:

1. **Enable authentication** - Use Streamlit's built-in auth (paid tier)
2. **Restrict database access** - Use IP whitelisting
3. **Use SSL/TLS** - Azure MySQL supports encrypted connections
4. **Never commit `.env`** - Already in `.gitignore` ✅
5. **Rotate credentials** - Change passwords regularly

### Public vs Private

**Current setup:** Anyone with the URL can access your app

**To make private:**
- Use Streamlit's authentication (Teams/Enterprise tier)
- Or add basic password protection in `app.py`
- Or use Azure AD authentication

## Monitoring & Maintenance

### View Logs
```
Streamlit Cloud Dashboard → Your App → Logs
```

### Restart App
```
Streamlit Cloud Dashboard → Your App → Reboot
```

### Update App
Just push to GitHub:
```bash
git add .
git commit -m "Update feature"
git push origin main
```

Streamlit auto-deploys on every push to `main`!

## Cost

### Streamlit Community Cloud
- **Free tier:** 1 private app, unlimited public apps
- **Limitations:** 1GB RAM, shared resources
- **Upgrade:** $20/month for more apps and resources

### Azure MySQL
- Check your Azure subscription for database costs
- Basic tier starts around $5-10/month

## Next Steps

1. ✅ Deploy to Streamlit Cloud
2. 🔒 Add authentication
3. 📊 Monitor usage and performance
4. 🚀 Share with friends (if you want)
5. 💡 Add features from the improvement list

## Support

- **Streamlit Docs:** https://docs.streamlit.io
- **Streamlit Forum:** https://discuss.streamlit.io
- **Azure Support:** https://portal.azure.com
