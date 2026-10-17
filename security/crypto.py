import os
import hashlib
import secrets
import json
import base64
import hmac
from datetime import datetime, timedelta

VAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KEY_FILE = os.path.join(VAULT_DIR, ".vault_key")

def get_or_create_master_key():
    """Retrieves or creates a local 256-bit (32-byte) AES master key."""
    os.makedirs(VAULT_DIR, exist_ok=True)
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            key = f.read()
            if len(key) == 32:
                return key
    
    # Generate new cryptographically secure 256-bit key
    key = secrets.token_bytes(32)
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    return key

# --- Password Security (PBKDF2-HMAC-SHA256 with 100,000 rounds) ---

def hash_password(password: str) -> tuple[str, str]:
    """Hashes password with a unique salt using 100k rounds of PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return key.hex(), salt

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Constant-time verification of password against stored hash."""
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return hmac.compare_digest(key.hex(), stored_hash)

# --- Biometric Descriptor Encryption (AES-256-GCM) ---

def encrypt_face_descriptor(descriptor: list[float]) -> tuple[bytes, bytes]:
    """Encrypts 128-d floating-point biometric descriptor using AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    
    key = get_or_create_master_key()
    aesgcm = AESGCM(key)
    iv = secrets.token_bytes(12)  # Standard 96-bit nonce for GCM
    
    # Serialize float list to compact JSON bytes
    payload = json.dumps(descriptor).encode('utf-8')
    ciphertext = aesgcm.encrypt(iv, payload, None)
    return ciphertext, iv

def decrypt_face_descriptor(ciphertext: bytes, iv: bytes) -> list[float]:
    """Decrypts ciphertext back into the 128-d biometric descriptor."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    
    key = get_or_create_master_key()
    aesgcm = AESGCM(key)
    decrypted_bytes = aesgcm.decrypt(iv, ciphertext, None)
    return json.loads(decrypted_bytes.decode('utf-8'))

# --- Secure Session Token Management (HMAC-SHA256 signed) ---

def generate_session_token(login_id: str, full_name: str, valid_hours: int = 4) -> str:
    """Generates a tamper-proof cryptographically signed session token."""
    key = get_or_create_master_key()
    expires_at = (datetime.utcnow() + timedelta(hours=valid_hours)).timestamp()
    payload = {
        "login_id": login_id,
        "full_name": full_name,
        "exp": expires_at,
        "nonce": secrets.token_hex(8)
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(key, payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"

def verify_session_token(token: str) -> dict | None:
    """Validates session token signature and expiration."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
        key = get_or_create_master_key()
        expected_sig = hmac.new(key, payload_b64.encode(), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return None  # Signature tampered
        
        payload_json = base64.urlsafe_b64decode(payload_b64.encode()).decode()
        payload = json.loads(payload_json)
        
        if datetime.utcnow().timestamp() > payload.get("exp", 0):
            return None  # Expired
            
        return payload
    except Exception:
        return None
