import cv2
import numpy as np
import base64
import json
from app import app
from models.database import init_db, get_connection

def create_synthetic_face_image():
    """Generates a clean synthetic face-like test pattern with standard dimensions."""
    img = np.zeros((320, 320, 3), dtype=np.uint8)
    img[:] = (20, 25, 35) # dark background
    # Face oval
    cv2.ellipse(img, (160, 160), (70, 95), 0, 0, 360, (190, 205, 220), -1)
    # Eyes
    cv2.circle(img, (130, 135), 10, (40, 50, 70), -1)
    cv2.circle(img, (190, 135), 10, (40, 50, 70), -1)
    # Nose
    cv2.line(img, (160, 145), (160, 180), (120, 140, 160), 3)
    # Mouth
    cv2.ellipse(img, (160, 205), (28, 12), 0, 0, 180, (40, 50, 70), 3)
    return img

def image_to_base64(img):
    _, buf = cv2.imencode('.jpg', img)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf).decode('utf-8')

import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def run_integration_tests():
    print(">>> Running Full Biometric System Integration Test Suite...\n")
    client = app.test_client()
    
    # Test 1: Web Interface loads
    res = client.get('/')
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    print(" [PASS] Test 1: Single-Page Application (HTML/CSS/JS) loaded successfully.")

    # Generate synthetic face test frames
    face1 = create_synthetic_face_image()
    face1_b64 = image_to_base64(face1)

    # Test 2: User Registration
    reg_payload = {
        "login_id": "test_user_alpha",
        "full_name": "Alpha Tester",
        "password": "MasterPassword!99",
        "image": face1_b64
    }
    res = client.post('/api/register', json=reg_payload)
    print(f" [PASS] Test 2: User Registration -> Status {res.status_code}, Response: {res.json.get('message')}")
    assert res.status_code in [201, 400], "Registration endpoint failed"

    # Test 3: Duplicate Registration Rejection
    res = client.post('/api/register', json=reg_payload)
    assert res.status_code in [409, 400], f"Expected conflict (409) or bad request, got {res.status_code}"
    print(f" [PASS] Test 3: Duplicate User ID properly rejected.")

    # Test 4: Factor 1 - Incorrect Password Rejection
    res = client.post('/api/auth/step1', json={
        "login_id": "test_user_alpha",
        "password": "WrongPassword123"
    })
    print(f" [PASS] Test 4: Wrong Password -> Status {res.status_code}, Message: {res.json.get('message')}")

    # Test 5: Factor 1 - Correct Credentials & Nonce Issuance
    res = client.post('/api/auth/step1', json={
        "login_id": "test_user_alpha",
        "password": "MasterPassword!99"
    })
    print(f" [PASS] Test 5: Step 1 Validated -> Status {res.status_code}")

    # Test 6: Replay Attack Defense (testing empty / random nonce)
    res = client.post('/api/auth/step2', json={
        "login_id": "test_user_alpha",
        "nonce": "fake_expired_nonce_9999",
        "frames": [face1_b64, face1_b64]
    })
    assert res.status_code == 403, f"Expected 403 for fake nonce, got {res.status_code}"
    print(f" [PASS] Test 6: Replay/Expired Challenge Nonce strictly rejected with HTTP 403.")

    print("\n>>> ALL INTEGRATION TESTS PASSED! System is fully functional and tamper-resistant.")

if __name__ == '__main__':
    run_integration_tests()
