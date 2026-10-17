import sqlite3
import os
import json
import secrets
from datetime import datetime, timedelta

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(os.path.dirname(DB_DIR), "data", "auth_vault.db")

def get_connection(db_path=DEFAULT_DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login_id TEXT UNIQUE NOT NULL COLLATE NOCASE,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            face_descriptor_encrypted BLOB NOT NULL,
            face_encryption_iv BLOB NOT NULL,
            avatar_path TEXT,
            failed_attempts INTEGER DEFAULT 0,
            lockout_until TEXT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT NULL,
            geo_latitude REAL NULL,
            geo_longitude REAL NULL,
            geo_accuracy REAL NULL,
            geo_address TEXT NULL,
            digital_fingerprint TEXT NULL,
            device_hash TEXT NULL,
            is_flagged INTEGER DEFAULT 0,
            flag_reason TEXT NULL
        )
    ''')

    # Safe column migrations if users table already exists
    cursor.execute("PRAGMA table_info(users)")
    existing_cols = {col["name"] for col in cursor.fetchall()}
    columns_to_add = [
        ("geo_latitude", "REAL NULL"),
        ("geo_longitude", "REAL NULL"),
        ("geo_accuracy", "REAL NULL"),
        ("geo_address", "TEXT NULL"),
        ("digital_fingerprint", "TEXT NULL"),
        ("device_hash", "TEXT NULL"),
        ("is_flagged", "INTEGER DEFAULT 0"),
        ("flag_reason", "TEXT NULL")
    ]
    for col_name, col_type in columns_to_add:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};")
    
    # 2. Immutable Security Audit Trail
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS security_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            distance_score REAL,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 3. Active Verification Nonces (Single-use challenge)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auth_challenges (
            nonce TEXT PRIMARY KEY,
            login_id TEXT NOT NULL,
            challenge_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    ''')

    # 4. Verified Geo-Tagged Photo Captures
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS geo_captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login_id TEXT NOT NULL,
            image_path TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            address TEXT,
            match_score REAL,
            fingerprint_hash TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create indexes for sub-millisecond lookups
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_login_id ON users(login_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_login_id ON security_audit_logs(login_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_challenges_nonce ON auth_challenges(nonce);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_geo_captures_login_id ON geo_captures(login_id);')
    
    conn.commit()
    conn.close()

def get_user_by_login_id(login_id, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE login_id = ?', (login_id.strip(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(
    login_id, full_name, password_hash, password_salt,
    face_descriptor_encrypted, face_iv, avatar_path=None,
    geo_data=None, fingerprint_data=None,
    db_path=DEFAULT_DB_PATH
):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    geo_data = geo_data or {}
    fingerprint_data = fingerprint_data or {}

    lat = geo_data.get("latitude")
    lon = geo_data.get("longitude")
    acc = geo_data.get("accuracy")
    addr = geo_data.get("address")
    fp_json = json.dumps(fingerprint_data) if fingerprint_data else None
    dev_hash = fingerprint_data.get("device_hash") or fingerprint_data.get("hardware", {}).get("canvas_hash")

    try:
        cursor.execute('''
            INSERT INTO users (
                login_id, full_name, password_hash, password_salt,
                face_descriptor_encrypted, face_encryption_iv, avatar_path,
                created_at, geo_latitude, geo_longitude, geo_accuracy, geo_address,
                digital_fingerprint, device_hash, is_flagged, flag_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
        ''', (
            login_id.strip(), full_name.strip(), password_hash, password_salt,
            face_descriptor_encrypted, face_iv, avatar_path, now_str,
            lat, lon, acc, addr, fp_json, dev_hash
        ))
        conn.commit()
        user_id = cursor.lastrowid
        return user_id
    finally:
        conn.close()

def is_user_locked_out(user):
    """Checks if the user account is currently locked out."""
    lockout_until = user.get('lockout_until')
    if not lockout_until:
        return False, 0
    try:
        lock_time = datetime.fromisoformat(lockout_until)
        now = datetime.utcnow()
        if now < lock_time:
            remaining_seconds = int((lock_time - now).total_seconds())
            return True, remaining_seconds
    except Exception:
        pass
    return False, 0

def increment_failed_attempts(login_id, max_attempts=5, lockout_minutes=15, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT failed_attempts FROM users WHERE login_id = ?', (login_id.strip(),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 0, False
    
    current_attempts = (row['failed_attempts'] or 0) + 1
    locked = False
    lockout_until = None
    
    if current_attempts >= max_attempts:
        locked = True
        lock_time = datetime.utcnow() + timedelta(minutes=lockout_minutes)
        lockout_until = lock_time.isoformat()
    
    cursor.execute('''
        UPDATE users 
        SET failed_attempts = ?, lockout_until = ?
        WHERE login_id = ?
    ''', (current_attempts, lockout_until, login_id.strip()))
    conn.commit()
    conn.close()
    return current_attempts, locked

def reset_failed_attempts(login_id, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    cursor.execute('''
        UPDATE users 
        SET failed_attempts = 0, lockout_until = NULL, last_login = ?
        WHERE login_id = ?
    ''', (now_str, login_id.strip()))
    conn.commit()
    conn.close()

def create_auth_challenge(login_id, challenge_type='BLINK_VERIFY', ttl_seconds=60, db_path=DEFAULT_DB_PATH):
    """Generates a cryptographically random single-use nonce for biometric verification."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Prune expired challenges first
    now = datetime.utcnow()
    cursor.execute('DELETE FROM auth_challenges WHERE expires_at < ?', (now.isoformat(),))
    
    nonce = secrets.token_hex(24)
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    
    cursor.execute('''
        INSERT INTO auth_challenges (nonce, login_id, challenge_type, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (nonce, login_id.strip(), challenge_type, now.isoformat(), expires_at))
    
    conn.commit()
    conn.close()
    return nonce

def consume_auth_challenge(nonce, login_id, db_path=DEFAULT_DB_PATH):
    """Validates challenge nonce and deletes it immediately to prevent replay attacks."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    
    cursor.execute('''
        SELECT * FROM auth_challenges 
        WHERE nonce = ? AND login_id = ? AND expires_at >= ?
    ''', (nonce, login_id.strip(), now_str))
    
    row = cursor.fetchone()
    if row:
        # Single use - delete immediately
        cursor.execute('DELETE FROM auth_challenges WHERE nonce = ?', (nonce,))
        conn.commit()
        conn.close()
        return True, dict(row)
    
    conn.close()
    return False, None

def log_audit_event(login_id, event_type, distance_score=None, ip_address=None, user_agent=None, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT INTO security_audit_logs (login_id, event_type, distance_score, ip_address, user_agent, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (login_id.strip(), event_type, distance_score, ip_address, user_agent, now_str))
    conn.commit()
    conn.close()

def get_recent_audit_logs(login_id, limit=8, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT event_type, distance_score, timestamp, ip_address 
        FROM security_audit_logs 
        WHERE login_id = ? 
        ORDER BY id DESC 
        LIMIT ?
    ''', (login_id.strip(), limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def flag_user(login_id, reason="Location or Digital Fingerprint Mismatch", db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET is_flagged = 1, flag_reason = ? 
        WHERE login_id = ?
    ''', (reason, login_id.strip()))
    conn.commit()
    conn.close()

def unflag_user(login_id, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET is_flagged = 0, flag_reason = NULL 
        WHERE login_id = ?
    ''', (login_id.strip(),))
    conn.commit()
    conn.close()

def update_user_fingerprint_baseline(login_id, geo_data=None, fingerprint_data=None, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    geo_data = geo_data or {}
    fingerprint_data = fingerprint_data or {}

    lat = geo_data.get("latitude")
    lon = geo_data.get("longitude")
    acc = geo_data.get("accuracy")
    addr = geo_data.get("address")
    fp_json = json.dumps(fingerprint_data) if fingerprint_data else None
    dev_hash = fingerprint_data.get("device_hash") or fingerprint_data.get("hardware", {}).get("canvas_hash")

    cursor.execute('''
        UPDATE users
        SET geo_latitude = ?, geo_longitude = ?, geo_accuracy = ?,
            geo_address = ?, digital_fingerprint = ?, device_hash = ?
        WHERE login_id = ?
    ''', (lat, lon, acc, addr, fp_json, dev_hash, login_id.strip()))
    conn.commit()
    conn.close()

def save_geo_capture(login_id, image_path, latitude, longitude, accuracy=None, address=None, match_score=None, fingerprint_hash=None, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    try:
        cursor.execute('''
            INSERT INTO geo_captures (
                login_id, image_path, latitude, longitude, accuracy, address, match_score, fingerprint_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (login_id.strip(), image_path, latitude, longitude, accuracy, address, match_score, fingerprint_hash, now_str))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_user_geo_captures(login_id, limit=20, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, login_id, image_path, latitude, longitude, accuracy, address, match_score, fingerprint_hash, created_at
        FROM geo_captures
        WHERE login_id = ?
        ORDER BY id DESC
        LIMIT ?
    ''', (login_id.strip(), limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

