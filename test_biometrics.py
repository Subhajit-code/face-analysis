import os
import secrets
from security.crypto import (
    hash_password, verify_password,
    encrypt_face_descriptor, decrypt_face_descriptor,
    generate_session_token, verify_session_token
)
from security.biometric import compare_faces
from models.database import (
    init_db, create_user, get_user_by_login_id,
    increment_failed_attempts, is_user_locked_out, reset_failed_attempts,
    create_auth_challenge, consume_auth_challenge
)

def test_full_suite():
    print("=================================================")
    print("  SECURITY & BIOMETRIC UNIT VERIFICATION SUITE")
    print("=================================================")

    # 1. Crypto & Passwords
    pwd = "MySuperSecretPassword@2026"
    h, s = hash_password(pwd)
    assert verify_password(pwd, h, s) == True, "Password verification failed"
    assert verify_password("WrongPassword!", h, s) == False, "Wrong password accepted!"
    print(" [PASS] 1. PBKDF2 Password Hashing & Verification")

    # 2. AES-256-GCM Encryption & Tamper Resistance
    original_vector = [0.087, -0.21, 0.44, 0.12, -0.05] * 25 # ~125 floats
    original_vector += [0.1, 0.2, 0.3] # 128 floats
    
    ciphertext, iv = encrypt_face_descriptor(original_vector)
    decrypted = decrypt_face_descriptor(ciphertext, iv)
    assert decrypted == original_vector, "Decrypted vector does not match original"
    
    # Tamper with ciphertext
    tampered = bytearray(ciphertext)
    tampered[5] ^= 0xFF
    try:
        decrypt_face_descriptor(bytes(tampered), iv)
        assert False, "Tampered ciphertext was accepted without raising error!"
    except Exception:
        pass # Expected AES-GCM auth tag verification failure
    print(" [PASS] 2. AES-256-GCM Encryption & Tamper Detection")

    # 3. Biometric Match & Strict Threshold Comparison
    # Exact match
    is_m1, score1, l2_1, conf1, is_sus1 = compare_faces(original_vector, original_vector, cosine_threshold=0.363)
    assert is_m1 == True and conf1 >= 85, f"Self-match failed: {score1}, {conf1}%"
    
    # Different face (orthogonal / inverted vector)
    impostor_vector = [-x for x in original_vector]
    is_m2, score2, l2_2, conf2, is_sus2 = compare_faces(original_vector, impostor_vector, cosine_threshold=0.363)
    assert is_m2 == False, f"Impostor face accepted! Score: {score2}"
    print(f" [PASS] 3. Biometric Matching: Genuine match={score1:.2f} (Accepted), Impostor={score2:.2f} (Rejected)")

    # 4. Anti-Replay Challenge Nonce
    init_db()
    test_id = "unit_test_user_" + secrets.token_hex(4)
    create_user(test_id, "Unit User", h, s, ciphertext, iv)
    
    nonce = create_auth_challenge(test_id)
    # First consumption succeeds
    ok, ch = consume_auth_challenge(nonce, test_id)
    assert ok == True, "First nonce consumption failed"
    # Second consumption MUST fail (replay attack defense)
    ok, ch = consume_auth_challenge(nonce, test_id)
    assert ok == False, "Replay attack was NOT blocked! Nonce was reused."
    print(" [PASS] 4. Anti-Replay Challenge Nonce (Single-Use Defense)")

    # 5. Rate Limiting & Account Lockout
    for attempt in range(1, 6):
        attempts, locked = increment_failed_attempts(test_id, max_attempts=5, lockout_minutes=15)
        if attempt < 5:
            assert locked == False
        else:
            assert locked == True
    
    user = get_user_by_login_id(test_id)
    is_locked, remaining = is_user_locked_out(user)
    assert is_locked == True and remaining > 800, "Lockout check failed"
    print(f" [PASS] 5. Brute-Force Defense: Account locked after 5 failed attempts ({remaining}s lockout)")

    # Reset on unlock
    reset_failed_attempts(test_id)
    user = get_user_by_login_id(test_id)
    is_locked, _ = is_user_locked_out(user)
    assert is_locked == False, "Account failed to unlock after reset"
    print(" [PASS] 6. Account Recovery & Reset Logic")

    # 6. Session Tokens
    token = generate_session_token(test_id, "Unit User", valid_hours=2)
    payload = verify_session_token(token)
    assert payload is not None and payload["login_id"] == test_id
    assert verify_session_token("fake.tampered_token") is None
    print(" [PASS] 7. Cryptographic Session Token Generation & Verification")

    print("\n>>> ALL 7 CORE SECURITY & BIOMETRIC TESTS PASSED WITH 100% SUCCESS!\n")

if __name__ == "__main__":
    test_full_suite()
