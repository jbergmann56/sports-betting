"""
Setup Script for Multi-Sport Betting Tracker
Initializes database and imports historical data
"""

import os
import sys
from database import DatabaseManager
from historical_importer import HistoricalDataImporter
import mysql.connector
from mysql.connector import Error


def load_env_file():
    """Load environment variables from .env file"""
    env_file = '.env'
    if not os.path.exists(env_file):
        print("❌ .env file not found!")
        print("Please create a .env file based on .env.template")
        return False
    
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key] = value
    
    print("✅ Environment variables loaded")
    return True


def test_db_connection():
    """Test database connection"""
    from config import DB_CONFIG
    
    print("\n🔌 Testing database connection...")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            print("✅ Database connection successful!")
            conn.close()
            return True
    except Error as e:
        print(f"❌ Database connection failed: {e}")
        return False


def create_database_schema():
    """Create database tables"""
    print("\n📊 Creating database schema...")
    
    from config import DB_CONFIG
    
    try:
        # Read schema file
        with open('schema.sql', 'r') as f:
            schema_sql = f.read()
        
        # Split into individual statements
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]
        
        # Execute each statement
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        for statement in statements:
            if statement:
                try:
                    cursor.execute(statement)
                    conn.commit()
                except Error as e:
                    # Ignore "table already exists" errors
                    if "already exists" not in str(e).lower():
                        print(f"Warning: {e}")
        
        cursor.close()
        conn.close()
        
        print("✅ Database schema created successfully!")
        return True
    
    except Exception as e:
        print(f"❌ Error creating schema: {e}")
        return False


def import_historical_data():
    """Import historical Excel data"""
    print("\n📥 Importing historical data...")
    
    # Check if uploads directory exists
    uploads_dir = '/mnt/user-data/uploads'
    if not os.path.exists(uploads_dir):
        uploads_dir = './uploads'
        if not os.path.exists(uploads_dir):
            print("⚠️  No uploads directory found. Skipping historical import.")
            print("   You can import data later using the Historical Importer.")
            return True
    
    # Look for Excel files
    excel_files = [f for f in os.listdir(uploads_dir) if f.endswith('.xlsx')]
    
    if not excel_files:
        print("⚠️  No Excel files found in uploads directory.")
        return True
    
    print(f"Found {len(excel_files)} Excel file(s):")
    for f in excel_files:
        print(f"  - {f}")
    
    import_choice = input("\nWould you like to import these files? (y/n): ")
    
    if import_choice.lower() != 'y':
        print("Skipping import.")
        return True
    
    try:
        db = DatabaseManager()
        importer = HistoricalDataImporter(db)
        
        # Import NHL file if exists
        nhl_file = next((f for f in excel_files if 'nhl' in f.lower()), None)
        if nhl_file:
            print(f"\n📊 Importing {nhl_file}...")
            file_path = os.path.join(uploads_dir, nhl_file)
            results = importer.import_nhl_excel(file_path)
            
            print("\nImport Results:")
            for key, count in results.items():
                print(f"  {key}: {count}")
        
        print("\n✅ Historical data import complete!")
        return True
    
    except Exception as e:
        print(f"❌ Error importing data: {e}")
        return False


def setup_streamlit_config():
    """Create Streamlit config file"""
    print("\n⚙️  Setting up Streamlit configuration...")
    
    config_dir = '.streamlit'
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    
    config_content = """[theme]
primaryColor = "#FF4B4B"
backgroundColor = "#0E1117"
secondaryBackgroundColor = "#262730"
textColor = "#FAFAFA"
font = "sans serif"

[server]
headless = true
port = 8501
"""
    
    with open(f'{config_dir}/config.toml', 'w') as f:
        f.write(config_content)
    
    print("✅ Streamlit config created")
    return True


def main():
    """Main setup process"""
    print("=" * 60)
    print("🎰 MULTI-SPORT BETTING TRACKER - SETUP")
    print("=" * 60)
    
    # Step 1: Load environment variables
    if not load_env_file():
        sys.exit(1)
    
    # Step 2: Test database connection
    if not test_db_connection():
        print("\n💡 Please check your .env file and database credentials.")
        sys.exit(1)
    
    # Step 3: Create database schema
    if not create_database_schema():
        sys.exit(1)
    
    # Step 4: Import historical data
    import_historical_data()
    
    # Step 5: Setup Streamlit
    setup_streamlit_config()
    
    print("\n" + "=" * 60)
    print("✅ SETUP COMPLETE!")
    print("=" * 60)
    print("\n🚀 To start the application, run:")
    print("   streamlit run app.py")
    print("\n📖 For more information, see README.md")
    print()


if __name__ == "__main__":
    main()
