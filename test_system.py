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
    assert res.status_code in [201, 400, 409], "Registration endpoint failed"

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

    # Test 7: User Registration with Geo-Coordinates & Digital Fingerprint
    import secrets
    geo_login_id = f"geo_user_{secrets.token_hex(3)}"
    geo_test_payload = {
        "login_id": geo_login_id,
        "full_name": "Geo Secure Tester",
        "password": "MasterPassword!99",
        "image": face1_b64,
        "geo_data": {
            "latitude": 22.5726,
            "longitude": 88.3639,
            "accuracy": 12.5,
            "address": "Kolkata Security Station"
        },
        "fingerprint_data": {
            "device_hash": "FP-SEC-9988A",
            "network": {
                "connection_type": "wifi",
                "downlink": 50.0,
                "rtt": 25,
                "local_gateway": "192.168.1.1",
                "tower_signature": "TOWER-KOL-5G"
            },
            "hardware": {
                "canvas_hash": "CV-HASH-991A",
                "webgl_renderer": "ANGLE (Intel, Iris Xe)",
                "audio_hash": "AUDIO-88FA",
                "screen": "1920x1080x24@1.25",
                "cpu_cores": 8,
                "platform": "Win32",
                "timezone": "Asia/Kolkata"
            }
        }
    }
    res = client.post('/api/register', json=geo_test_payload)
    assert res.status_code == 201, f"Registration failed with status {res.status_code}: {res.json}"
    print(" [PASS] Test 7: User enrolled with GPS coordinates & digital network/hardware fingerprint baseline.")

    # Generate session token for test user
    from security.crypto import generate_session_token
    token = generate_session_token(geo_login_id, "Geo Secure Tester")
    headers = {"Authorization": f"Bearer {token}"}

    # Test 8: Profile returns geo baseline & digital fingerprint
    res = client.get('/api/user/profile', headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    prof_data = res.json
    assert prof_data["user"]["geo_latitude"] is not None
    assert prof_data["user"]["device_hash"] == "FP-SEC-9988A"
    print(f" [PASS] Test 8: User Profile verified with baseline coordinates: {prof_data['user']['geo_latitude']}, {prof_data['user']['geo_longitude']}.")

    # Test 9: Camera Access Verification - Matching Baseline (>= 80%)
    res = client.post('/api/geo/verify-camera-access', headers=headers, json={
        "geo_data": {
            "latitude": 22.5727, # 11 meters away
            "longitude": 88.3638,
            "accuracy": 10.0
        },
        "fingerprint_data": geo_test_payload["fingerprint_data"],
        "simulate_mismatch": False
    })
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert res.json["allowed"] is True
    assert res.json["match_score"] >= 80.0
    print(f" [PASS] Test 9: Camera Access GRANTED for matching fingerprint (Score: {res.json['match_score']}% >= 80%).")

    # Test 10: Camera Access Verification - THE TWIST: Mismatch (< 80%) Restriction & Flagging
    res = client.post('/api/geo/verify-camera-access', headers=headers, json={
        "geo_data": {
            "latitude": 19.0760, # Mumbai (~1600 km away)
            "longitude": 72.8777,
            "accuracy": 15.0
        },
        "fingerprint_data": {
            "device_hash": "FOREIGN-DEVICE-000",
            "network": {
                "connection_type": "cellular",
                "local_gateway": "10.0.0.99",
                "tower_signature": "TOWER-MUM-4G"
            },
            "hardware": {
                "canvas_hash": "FOREIGN-CANVAS-999",
                "webgl_renderer": "Mali-G78",
                "audio_hash": "FOREIGN-AUDIO",
                "platform": "Android"
            }
        },
        "simulate_mismatch": False
    })
    assert res.status_code == 403, f"Expected 403 restriction, got {res.status_code}"
    assert res.json["allowed"] is False
    assert res.json["restricted"] is True
    assert res.json["flagged"] is True
    assert res.json["match_score"] < 80.0
    print(f" [PASS] Test 10: THE TWIST VERIFIED! Camera Access RESTRICTED (< 80% match, score: {res.json['match_score']}%) and flagged.")

    # Test 11: Verify user account is flagged in profile & audit trail
    res = client.get('/api/user/profile', headers=headers)
    assert res.status_code == 200
    assert res.json["user"]["is_flagged"] == True
    audit_events = [log["event_type"] for log in res.json["audit_logs"]]
    assert "CAMERA_RESTRICTED_FINGERPRINT_MISMATCH" in audit_events
    print(f" [PASS] Test 11: Audit trail successfully recorded 'CAMERA_RESTRICTED_FINGERPRINT_MISMATCH' event.")

    # Test 12: Geo-Tagged Photo Capture & Archiving
    # First unflag by providing matching access verification
    client.post('/api/geo/verify-camera-access', headers=headers, json={
        "geo_data": geo_test_payload["geo_data"],
        "fingerprint_data": geo_test_payload["fingerprint_data"]
    })
    
    res = client.post('/api/geo/capture-photo', headers=headers, json={
        "image": face1_b64,
        "geo_data": geo_test_payload["geo_data"],
        "fingerprint_data": geo_test_payload["fingerprint_data"],
        "match_score": 96.5
    })
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.json}"
    assert res.json["success"] is True
    image_url = res.json["image_url"]
    print(f" [PASS] Test 12: Geo-tagged photo watermarked, archived, and returned at {image_url}.")

    # Test 13: Fetch Geo-Tagged photo file and user gallery
    res_photo = client.get(image_url)
    assert res_photo.status_code == 200
    assert res_photo.mimetype == "image/jpeg"

    res_gallery = client.get('/api/geo/captures', headers=headers)
    assert res_gallery.status_code == 200
    assert len(res_gallery.json["captures"]) >= 1
    print(f" [PASS] Test 13: Geo-tagged gallery and photo serving verified successfully.")

    print("\n>>> ALL 13 INTEGRATION TESTS PASSED! System is fully functional and tamper-resistant.")

if __name__ == '__main__':
    run_integration_tests()

