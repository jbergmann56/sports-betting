# 🚀 Streamlit Deployment Checklist

## Pre-Deployment Checklist

- [ ] **Code is on GitHub** ✅ (Already done: https://github.com/jbergmann56/app)
- [ ] **`.env` is in `.gitignore`** ✅ (Already added)
- [ ] **`requirements.txt` exists** ✅ (Already exists)
- [ ] **Azure MySQL firewall configured** (See below)
- [ ] **Test app locally**: `streamlit run app.py`

## Azure MySQL Configuration

### Option 1: Allow All IPs (Easiest, Less Secure)
```sql
-- In Azure Portal:
-- Settings → Connection Security
-- Add firewall rule:
--   Name: "Streamlit Cloud"
--   Start IP: 0.0.0.0
--   End IP: 255.255.255.255
```

### Option 2: Whitelist Streamlit IPs (More Secure)
Streamlit Cloud uses dynamic IPs, so Option 1 is typically needed.

## Deployment Steps

### 1. Push Latest Code
```bash
cd "c:\Users\jberg\OneDrive\Gambling\app"

# Check status
git status

# Add files
git add .
git commit -m "Prepare for Streamlit deployment"
git push origin main
```

### 2. Deploy on Streamlit Cloud

1. Go to: **https://share.streamlit.io**
2. Click **"Sign in with GitHub"**
3. Click **"New app"**
4. Fill in:
   - **Repository:** `jbergmann56/app`
   - **Branch:** `main`
   - **Main file:** `app.py`
5. Click **"Advanced settings"** (IMPORTANT!)
6. In the **"Secrets"** box, paste:

```toml
AZURE_MYSQL_HOST = "your-server.mysql.database.azure.com"
AZURE_MYSQL_USER = "your-username@your-server"
AZURE_MYSQL_PASSWORD = "your-actual-password"
AZURE_MYSQL_DATABASE = "betting_tracker"
AZURE_MYSQL_PORT = "3306"
```

7. Click **"Deploy!"**

### 3. Wait for Deployment
- Takes 2-5 minutes
- Watch the logs for any errors
- Look for: "Your app is live!" message

### 4. Test Your App
- Click the URL (e.g., `https://jbergmann56-app-app-xyz123.streamlit.app`)
- Try navigating to different pages
- Test database connection (Settings → Test Database Connection)
- Try importing a game
- Place a test bet

## Post-Deployment

### Share Your App
- [ ] Bookmark the URL
- [ ] Share with trusted people only (contains your betting data!)

### Monitor
- [ ] Check logs in Streamlit dashboard
- [ ] Monitor database connections in Azure
- [ ] Set up alerts for errors (optional)

### Security
- [ ] Consider adding password protection (see below)
- [ ] Don't share the URL publicly
- [ ] Rotate database password every 90 days

## Adding Password Protection (Optional)

Add this to the top of `app.py`:

```python
import streamlit as st

# Simple password protection
def check_password():
    """Returns True if the user has entered the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

if not check_password():
    st.stop()

# Rest of your app code...
```

Then add to Streamlit secrets:
```toml
APP_PASSWORD = "your-secure-password"
```

## Troubleshooting

### ❌ "Can't connect to MySQL server"
**Fix:**
1. Check Azure firewall allows 0.0.0.0-255.255.255.255
2. Verify secrets are correct (no typos)
3. Ensure database is running

### ❌ "ModuleNotFoundError"
**Fix:**
1. Check `requirements.txt` has all dependencies
2. Push updated `requirements.txt` to GitHub
3. Reboot app in Streamlit dashboard

### ❌ "Out of memory"
**Fix:**
1. Free tier has 1GB RAM limit
2. Add `@st.cache_data` to expensive functions
3. Limit query results (add LIMIT to SQL)
4. Consider upgrading Streamlit tier

### ❌ App won't load
**Fix:**
1. Check logs in Streamlit dashboard
2. Test locally first: `streamlit run app.py`
3. Ensure `app.py` is at repository root

## Auto-Deploy

Streamlit automatically redeploys when you push to GitHub:

```bash
# Make changes locally
# Test: streamlit run app.py

# Commit and push
git add .
git commit -m "Add new feature"
git push origin main

# Streamlit auto-deploys in 30 seconds!
```

## Your App URLs

- **Local:** http://localhost:8501
- **Production:** https://[your-app-url].streamlit.app (you'll get this after deployment)

## Resources

- 📚 [Streamlit Docs](https://docs.streamlit.io/streamlit-community-cloud)
- 💬 [Streamlit Forum](https://discuss.streamlit.io)
- 🐛 [Report Issues](https://github.com/streamlit/streamlit/issues)

## Quick Commands

```bash
# Test locally
cd "c:\Users\jberg\OneDrive\Gambling\app"
streamlit run app.py

# Deploy updates
git add .
git commit -m "Update"
git push origin main

# View logs
# Go to share.streamlit.io → Your app → Logs
```

---

**Ready to deploy? Follow the steps above!** 🚀

**Estimated time:** 10-15 minutes
