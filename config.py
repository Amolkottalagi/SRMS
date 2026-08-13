import os
import pymysql

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'srms_super_secret_key_12345')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'password')
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))
    MYSQL_DB = os.environ.get('MYSQL_DB', 'srms')

    # Detect if MySQL is available, otherwise fallback to SQLite
    use_sqlite = True
    try:
        # Attempt connection
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            port=MYSQL_PORT,
            connect_timeout=2
        )
        # Check if database srms exists
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB}")
        cursor.close()
        conn.close()
        use_sqlite = False
    except Exception:
        # Fallback to SQLite if MySQL is not available or credentials fail
        pass

    if use_sqlite:
        SQLALCHEMY_DATABASE_URI = "sqlite:///srms.db"
    else:
        SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
