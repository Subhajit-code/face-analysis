import os
import cv2
import json
import random
import secrets
import urllib.request
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, send_file, make_response

load_dotenv()
from models.database import (
    init_db, get_user_by_login_id, create_user,
    is_user_locked_out, increment_failed_attempts, reset_failed_attempts,
    create_auth_challenge, consume_auth_challenge,
    log_audit_event, get_recent_audit_logs,
    flag_user, unflag_user, update_user_fingerprint_baseline,
    save_geo_capture, get_user_geo_captures,
    DEFAULT_DB_PATH
)
from security.crypto import (
    hash_password, verify_password,
    encrypt_face_descriptor, decrypt_face_descriptor,
    generate_session_token, verify_session_token
)
from security.liveness import decode_base64_image, check_image_quality, verify_liveness, verify_head_turn_challenge
from security.biometric import detect_faces, extract_single_face, compare_faces, compute_yaw_proxy, compute_face_quality
from security.ssl_cert import ensure_ssl_certificates, get_lan_ip
from security.geofingerprint import evaluate_geo_fingerprint_match, apply_geotag_watermark, reverse_geocode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
AVATARS_DIR = os.path.join(DATA_DIR, "avatars")
ALERTS_DIR = os.path.join(DATA_DIR, "alerts")
GEOTAG_DIR = os.path.join(DATA_DIR, "geotagged")
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(ALERTS_DIR, exist_ok=True)
os.makedirs(GEOTAG_DIR, exist_ok=True)

from werkzeug.middleware.proxy_fix import ProxyFix
from flask_cors import CORS

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.urandom(32)
# Ensure cloud reverse proxy headers (HTTPS, client IP) are recognized
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Enable CORS for Netlify frontend deployments & cross-origin requests
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# Initialize database schema on startup
init_db()

@app.route("/health")
@app.route("/api/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "FaceVault Biometric 2FA Engine",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

def load_env():
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and v:
                            os.environ[k] = v
        except Exception:
            pass

load_env()

def get_client_ip():
    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1")
    return raw_ip.split(",")[0].strip()

def lookup_ip_geolocation(ip_address=""):
    """
    Multi-provider IP geolocation lookup helper.
    Supports commercial APIs (IPinfo, Google Maps) if key provided in .env,
    with freeipapi and ip-api fallbacks.
    """
    clean_ip = (ip_address or "").strip()
    is_private_or_local = (not clean_ip) or clean_ip in ("127.0.0.1", "localhost", "::1") or clean_ip.startswith(("10.", "192.168.", "172."))

    # 1. Commercial IPinfo.io (if user provided token)
    ipinfo_token = os.environ.get("IPINFO_TOKEN")
    if ipinfo_token:
        try:
            url = f"https://ipinfo.io/json?token={ipinfo_token}" if is_private_or_local else f"https://ipinfo.io/{clean_ip}/json?token={ipinfo_token}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode())
                loc = data.get("loc", "").split(",")
                if len(loc) == 2:
                    city = data.get("city") or "Durgapur"
                    region = data.get("region") or "West Bengal"
                    country = data.get("country") or "India"
                    return {
                        "latitude": float(loc[0]),
                        "longitude": float(loc[1]),
                        "accuracy": 300.0,
                        "city": f"{city}, {region}, {country}",
                        "region": region,
                        "country": country,
                        "isp": data.get("org", "Commercial IPinfo")
                    }
        except Exception:
            pass

    # 2. freeipapi.com (Accurately resolves Indian telecom ISP pools e.g. Airtel/Jio in Durgapur, West Bengal)
    try:
        url = "https://freeipapi.com/api/json" if is_private_or_local else f"https://freeipapi.com/api/json/{clean_ip}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            if data.get("latitude") is not None and data.get("longitude") is not None:
                city = data.get("cityName") or "Durgapur"
                region = data.get("regionName") or "West Bengal"
                country = data.get("countryName") or "India"
                return {
                    "latitude": float(data.get("latitude")),
                    "longitude": float(data.get("longitude")),
                    "accuracy": 600.0,
                    "city": f"{city}, {region}, {country}",
                    "region": region,
                    "country": country,
                    "isp": data.get("asnOrganization", "")
                }
    except Exception:
        pass

    # 2. Secondary fallback: ip-api.com
    try:
        url = "http://ip-api.com/json" if is_private_or_local else f"http://ip-api.com/json/{clean_ip}"
        req = urllib.request.Request(url, headers={"User-Agent": "FaceVault-Geo/1.0"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                city = data.get("city") or "Durgapur"
                region = data.get("regionName") or "West Bengal"
                return {
                    "latitude": float(data.get("lat")),
                    "longitude": float(data.get("lon")),
                    "accuracy": 1000.0,
                    "city": f"{city}, {region}",
                    "region": region,
                    "country": data.get("country", "India"),
                    "isp": data.get("isp", "")
                }
    except Exception:
        pass
    return None

# --- Web Interface ---

@app.route("/")
def index():
    return render_template("index.html")

# --- Authentication APIs ---

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    login_id = (data.get("login_id") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    password = (data.get("password") or "").strip()
    image_b64 = data.get("image")
    
    if not login_id or not full_name or not password or not image_b64:
        return jsonify({"success": False, "message": "All fields (Login ID, Full Name, Password, and Face Capture) are required."}), 400
    
    if len(login_id) < 3:
        return jsonify({"success": False, "message": "Login ID must be at least 3 characters long."}), 400
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters long."}), 400
    
    # Check if user already exists
    existing = get_user_by_login_id(login_id)
    if existing:
        return jsonify({"success": False, "message": f"Login ID '{login_id}' is already registered. Please choose another."}), 409
    
    # Decode and validate face capture
    try:
        img = decode_base64_image(image_b64)
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to process image: {str(e)}"}), 400
    
    # Quality check & low light auto enhancement
    ok, quality_msg, proc_img = check_image_quality(img)
    if not ok:
        return jsonify({"success": False, "message": quality_msg}), 400
    
    # Biometric extraction (strict 1 face only)
    ok, face_msg, descriptor, bbox, aligned_crop = extract_single_face(proc_img)
    if not ok:
        return jsonify({"success": False, "message": face_msg}), 400
    
    # Save avatar preview
    avatar_filename = f"{login_id}.jpg"
    avatar_path = os.path.join(AVATARS_DIR, avatar_filename)
    cv2.imwrite(avatar_path, aligned_crop)
    
    # Encrypt biometric descriptor with AES-256-GCM
    encrypted_vector, iv = encrypt_face_descriptor(descriptor)
    
    # Hash password with PBKDF2-HMAC-SHA256
    pwd_hash, salt = hash_password(password)
    
    # Capture geo coordinates and digital network/device fingerprint
    geo_data = data.get("geo_data") or {}
    fingerprint_data = data.get("fingerprint_data") or {}
    
    # Enrich with server-side network & IP info if not present
    client_ip = get_client_ip()
    if not fingerprint_data.get("network"):
        fingerprint_data["network"] = {}
    fingerprint_data["network"]["ip"] = client_ip

    # Save to SQLite
    try:
        user_id = create_user(
            login_id=login_id,
            full_name=full_name,
            password_hash=pwd_hash,
            password_salt=salt,
            face_descriptor_encrypted=encrypted_vector,
            face_iv=iv,
            avatar_path=avatar_filename,
            geo_data=geo_data,
            fingerprint_data=fingerprint_data
        )
        log_audit_event(login_id, "USER_REGISTERED", ip_address=client_ip)
        return jsonify({
            "success": True,
            "message": f"Account for '{full_name}' successfully created with digital fingerprint baseline! You may now log in.",
            "user_id": user_id
        }), 201
    except Exception as e:
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

@app.route("/api/auth/step1", methods=["POST"])
def auth_step1():
    """Factor 1: Validates Login ID and Password, issues anti-replay challenge nonce."""
    data = request.get_json() or {}
    login_id = (data.get("login_id") or "").strip()
    password = (data.get("password") or "").strip()
    
    if not login_id or not password:
        return jsonify({"success": False, "message": "Please enter both Login ID and Password."}), 400
    
    user = get_user_by_login_id(login_id)
    if not user:
        # Subtle timing resistance
        return jsonify({"success": False, "message": "Invalid Login ID or Password."}), 401
    
    # Check account lockout
    locked, remaining_seconds = is_user_locked_out(user)
    if locked:
        mins = max(1, remaining_seconds // 60)
        return jsonify({
            "success": False,
            "locked": True,
            "message": f"Account locked due to excessive failed attempts. Try again in {mins} minute(s)."
        }), 403
    
    # Verify password
    if not verify_password(password, user["password_hash"], user["password_salt"]):
        attempts, is_now_locked = increment_failed_attempts(login_id)
        log_audit_event(login_id, "INVALID_PASSWORD", ip_address=get_client_ip())
        if is_now_locked:
            return jsonify({
                "success": False,
                "locked": True,
                "message": "Account has been locked for 15 minutes due to 5 consecutive failed attempts."
            }), 403
        remaining = 5 - attempts
        return jsonify({
            "success": False,
            "message": f"Invalid Login ID or Password. ({remaining} attempts remaining before lockout)."
        }), 401
    
    # Password verified! Issue a random active liveness challenge (defeats photo/video replay,
    # since the direction is chosen now and only revealed to the user at this moment).
    turn_direction = random.choice(["TURN_LEFT", "TURN_RIGHT"])
    nonce = create_auth_challenge(login_id, challenge_type=turn_direction, ttl_seconds=60)

    return jsonify({
        "success": True,
        "nonce": nonce,
        "full_name": user["full_name"],
        "challenge_direction": "LEFT" if turn_direction == "TURN_LEFT" else "RIGHT",
        "message": "Credentials verified. Please look directly at the camera for biometric scan."
    })

@app.route("/api/auth/step2", methods=["POST"])
def auth_step2():
    """Factor 2: Liveness detection + AES-256 Biometric face comparison."""
    data = request.get_json() or {}
    login_id = (data.get("login_id") or "").strip()
    nonce = (data.get("nonce") or "").strip()
    frames_b64 = data.get("frames") or []
    
    if not login_id or not nonce or not frames_b64:
        return jsonify({"success": False, "message": "Missing biometric verification payload or frames."}), 400
    
    # Anti-Replay: Consume nonce immediately
    valid_nonce, challenge = consume_auth_challenge(nonce, login_id)
    if not valid_nonce:
        log_audit_event(login_id, "REPLAY_ATTACK_ATTEMPT", ip_address=get_client_ip())
        return jsonify({"success": False, "message": "Session expired or invalid challenge nonce. Please log in again."}), 403
    
    user = get_user_by_login_id(login_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    
    # Check lockout
    locked, remaining_seconds = is_user_locked_out(user)
    if locked:
        return jsonify({"success": False, "message": "Account is locked."}), 403
    
    # Decode submitted frames with automatic low-light enhancement
    decoded_frames = []
    face_boxes = []
    frame_descriptors = []
    yaw_proxies = []

    for f_b64 in frames_b64:
        try:
            img = decode_base64_image(f_b64)
            _, _, proc_img = check_image_quality(img)
            face_count, faces = detect_faces(proc_img)
            if face_count == 1:
                desc, bbox, _ = extract_single_face(proc_img)[2:]
                quality_ok, _, _ = compute_face_quality(proc_img, bbox)
                if not quality_ok:
                    continue
                decoded_frames.append(proc_img)
                face_boxes.append(bbox)
                frame_descriptors.append(desc)
                yaw_proxies.append(compute_yaw_proxy(faces[0]))
        except Exception:
            continue

    if len(decoded_frames) == 0:
        increment_failed_attempts(login_id)
        log_audit_event(login_id, "NO_FACE_IN_SCAN", ip_address=get_client_ip())
        return jsonify({"success": False, "message": "No clear face detected during camera scan. Please ensure your face is inside the frame."}), 400

    # Active liveness challenge: verify the user actually turned their head in the direction
    # that was randomly assigned at login step 1 (unpredictable, so a photo/video replay can't
    # have been prepared in advance to satisfy it).
    challenge_direction = (challenge or {}).get("challenge_type")
    if challenge_direction in ("TURN_LEFT", "TURN_RIGHT"):
        turn_ok, turn_msg = verify_head_turn_challenge(yaw_proxies, challenge_direction)
        if not turn_ok:
            increment_failed_attempts(login_id)
            log_audit_event(login_id, "HEAD_TURN_CHALLENGE_FAILED", ip_address=get_client_ip())
            return jsonify({
                "success": False,
                "liveness_failed": True,
                "message": f"Active Liveness Challenge: {turn_msg}"
            }), 403

    # Liveness / Anti-spoofing analysis across frames
    if len(decoded_frames) >= 2:
        is_live, liveness_msg, motion_score = verify_liveness(decoded_frames, face_boxes)
        if not is_live:
            increment_failed_attempts(login_id)
            log_audit_event(login_id, "LIVENESS_FAILED", ip_address=get_client_ip())
            return jsonify({
                "success": False,
                "liveness_failed": True,
                "message": f"Biometric Anti-Spoofing: {liveness_msg}"
            }), 403
    
    # Decrypt registered face descriptor from vault
    try:
        stored_data = decrypt_face_descriptor(
            user["face_descriptor_encrypted"],
            user["face_encryption_iv"]
        )
        if isinstance(stored_data, dict):
            registered_desc = stored_data.get("vector") or stored_data.get("embedding")
        else:
            registered_desc = stored_data
    except Exception as e:
        return jsonify({"success": False, "message": f"Vault decryption error: {str(e)}"}), 500
    
    # Robust biometric verification (posture, dress, and lighting invariant).
    # The registered face embedding is captured near-frontal at enrollment, and SFace's accuracy
    # drops measurably off-angle. Since the active liveness challenge deliberately asks the user
    # to turn their head mid-scan, matching identity against those turned frames against a frontal
    # baseline would cause false rejects unrelated to who the person is. So identity matching only
    # considers frames close to center (low yaw); the turned frames are still used for the
    # head-turn liveness check above, just not for face-identity comparison.
    FRONTAL_YAW_LIMIT = 0.06
    frontal_descriptors = [
        frame_descriptors[i] for i in range(len(frame_descriptors))
        if i < len(yaw_proxies) and abs(yaw_proxies[i]) <= FRONTAL_YAW_LIMIT
    ]
    match_candidates = frontal_descriptors if frontal_descriptors else frame_descriptors

    best_match = False
    best_cosine = -1.0
    best_conf = 0
    scores = []
    impersonation_suspected = False

    for desc in match_candidates:
        is_m, cos_sim, l2_d, conf, is_suspect = compare_faces(
            registered_desc, desc,
            min_confidence=80 # Strict user requirement: Must be at least 80%
        )
        scores.append(cos_sim)
        if conf > best_conf:
            best_conf = conf
            best_cosine = cos_sim
        if is_m and conf >= 80:
            best_match = True
        if is_suspect:
            impersonation_suspected = True

    # STRICT SECURITY RULE: ONLY enter if match confidence is AT LEAST 80%
    if best_match and best_conf >= 80:
        # SUCCESS!
        reset_failed_attempts(login_id)
        log_audit_event(login_id, "LOGIN_SUCCESS", distance_score=best_cosine, ip_address=get_client_ip())
        token = generate_session_token(login_id, user["full_name"])
        
        return jsonify({
            "success": True,
            "matched": True,
            "confidence": best_conf,
            "similarity": round(best_cosine, 3),
            "token": token,
            "user": {
                "login_id": user["login_id"],
                "full_name": user["full_name"],
                "avatar": f"/api/avatar/{user['login_id']}"
            },
            "message": f"Face Matched! Verified with {best_conf}% confidence (>= 80% required). Welcome back, {user['full_name']}."
        })
    else:
        # MISMATCH OR INSUFFICIENT CONFIDENCE (< 80%)
        attempts, is_now_locked = increment_failed_attempts(login_id)
        
        # Issue fresh challenge nonce (with a freshly randomized head-turn direction) so the
        # user can immediately retry without re-entering password, while keeping the active
        # liveness challenge in force on the retry too.
        new_nonce = None
        new_turn_direction = None
        if not is_now_locked:
            new_turn_direction = random.choice(["TURN_LEFT", "TURN_RIGHT"])
            new_nonce = create_auth_challenge(login_id, challenge_type=new_turn_direction, ttl_seconds=90)
        
        # Save photographic evidence of the impostor
        try:
            timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            evidence_file = f"impostor_{login_id}_{timestamp_str}.jpg"
            cv2.imwrite(os.path.join(ALERTS_DIR, evidence_file), decoded_frames[0])
        except Exception:
            pass
        
        lockout_msg = " Account locked due to repeated failures." if is_now_locked else ""
        
        if impersonation_suspected:
            # Impostor with similar face
            log_audit_event(login_id, "SECURITY_IMPOSTOR_ALERT", distance_score=best_cosine, ip_address=get_client_ip())
            return jsonify({
                "success": False,
                "matched": False,
                "new_nonce": new_nonce,
                "new_challenge_direction": "LEFT" if new_turn_direction == "TURN_LEFT" else ("RIGHT" if new_turn_direction == "TURN_RIGHT" else None),
                "impersonation_caught": True,
                "confidence": best_conf,
                "message": f"SECURITY ALERT: Similar face detected but confidence ({best_conf}%) is below the required 80% threshold!{lockout_msg}"
            }), 403
        else:
            log_audit_event(login_id, "FACE_MISMATCH", distance_score=best_cosine, ip_address=get_client_ip())
            return jsonify({
                "success": False,
                "matched": False,
                "new_nonce": new_nonce,
                "new_challenge_direction": "LEFT" if new_turn_direction == "TURN_LEFT" else ("RIGHT" if new_turn_direction == "TURN_RIGHT" else None),
                "confidence": best_conf,
                "message": f"Face Mismatch! Match score {best_conf}% is below the required 80% threshold.{lockout_msg}"
            }), 403

# --- User Session & Dashboard Profile ---

@app.route("/api/user/profile", methods=["GET"])
def get_profile():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_session_token(token)
    
    if not payload:
        return jsonify({"success": False, "message": "Unauthorized or session expired."}), 401
    
    login_id = payload["login_id"]
    user = get_user_by_login_id(login_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    
    logs = get_recent_audit_logs(login_id, limit=8)
    geo_captures = get_user_geo_captures(login_id, limit=12)
    for c in geo_captures:
        c["image_url"] = f"/api/geo/photo/{c['image_path']}"
    
    raw_fp = user.get("digital_fingerprint")
    parsed_fp = None
    if raw_fp:
        try:
            parsed_fp = json.loads(raw_fp)
        except Exception:
            parsed_fp = None

    return jsonify({
        "success": True,
        "user": {
            "login_id": user["login_id"],
            "full_name": user["full_name"],
            "created_at": user["created_at"],
            "last_login": user["last_login"],
            "avatar": f"/api/avatar/{user['login_id']}",
            "is_flagged": bool(user.get("is_flagged")),
            "flag_reason": user.get("flag_reason"),
            "geo_latitude": user.get("geo_latitude"),
            "geo_longitude": user.get("geo_longitude"),
            "geo_accuracy": user.get("geo_accuracy"),
            "geo_address": user.get("geo_address"),
            "device_hash": user.get("device_hash")
        },
        "digital_fingerprint": parsed_fp,
        "audit_logs": logs,
        "geo_captures": geo_captures
    })

# --- Geo-Tagged Camera & Digital Fingerprint Access Control ---

@app.route("/api/geo/verify-camera-access", methods=["POST"])
def verify_camera_access():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_session_token(token)
    if not payload:
        return jsonify({"success": False, "message": "Unauthorized or session expired."}), 401

    login_id = payload["login_id"]
    user = get_user_by_login_id(login_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    data = request.get_json() or {}
    curr_geo = data.get("geo_data") or {}
    curr_fp = data.get("fingerprint_data") or {}
    simulation_mismatch = bool(data.get("simulate_mismatch"))
    client_ip = get_client_ip()

    if not curr_fp.get("network"):
        curr_fp["network"] = {}
    if not curr_fp["network"].get("ip"):
        curr_fp["network"]["ip"] = client_ip

    # Reconstruct registered baseline
    reg_fp_raw = user.get("digital_fingerprint")
    reg_fp = {}
    if reg_fp_raw:
        try:
            reg_fp = json.loads(reg_fp_raw)
        except Exception:
            reg_fp = {}

    reg_baseline = {
        "latitude": user.get("geo_latitude"),
        "longitude": user.get("geo_longitude"),
        "accuracy": user.get("geo_accuracy"),
        "address": user.get("geo_address"),
        "network": reg_fp.get("network") or {},
        "hardware": reg_fp.get("hardware") or {}
    }

    # Auto-enroll if user registered before geo features
    if user.get("geo_latitude") is None and curr_geo.get("latitude") is not None:
        update_user_fingerprint_baseline(login_id, curr_geo, curr_fp)
        reg_baseline["latitude"] = curr_geo.get("latitude")
        reg_baseline["longitude"] = curr_geo.get("longitude")
        reg_baseline["network"] = curr_fp.get("network") or {}
        reg_baseline["hardware"] = curr_fp.get("hardware") or {}

    current_data = {
        "latitude": curr_geo.get("latitude"),
        "longitude": curr_geo.get("longitude"),
        "accuracy": curr_geo.get("accuracy"),
        "network": curr_fp.get("network") or {},
        "hardware": curr_fp.get("hardware") or {}
    }

    # If simulation mode is explicitly toggled by tester to demonstrate the <80% restriction
    if simulation_mismatch:
        eval_result = {
            "matched": False,
            "score": 36.5,
            "threshold": 80.0,
            "distance_meters": 5200.0,
            "distance_km": 5.2,
            "subscores": {"geo": 0.0, "network": 25.0, "hardware": 95.0},
            "reasons": [
                "Geographic discrepancy: Location deviates by 5.2 km from registered sector (Geo match: 0%).",
                "Network variance: Registered Wi-Fi router & local gateway unreachable; foreign cell tower detected."
            ],
            "message": "Security Alert: Digital fingerprint mismatch. Match score is 36.5%, below the required 80% threshold."
        }
    else:
        eval_result = evaluate_geo_fingerprint_match(reg_baseline, current_data)

    match_score = eval_result["score"]
    is_match = eval_result["matched"]

    if not is_match:
        # TWIST: RESTRICT CAMERA & PLAY AUDIO & FLAG USER IN AUDIT TRAIL
        flag_user(login_id, f"Digital Fingerprint Mismatch: {match_score}% (< 80% required)")
        log_audit_event(
            login_id,
            "CAMERA_RESTRICTED_FINGERPRINT_MISMATCH",
            distance_score=round(match_score / 100.0, 3),
            ip_address=client_ip
        )
        return jsonify({
            "success": False,
            "allowed": False,
            "restricted": True,
            "flagged": True,
            "match_score": match_score,
            "threshold": 80.0,
            "distance_km": eval_result.get("distance_km"),
            "subscores": eval_result.get("subscores"),
            "reasons": eval_result.get("reasons"),
            "message": f"Security Alert: Your digital fingerprint and geographical coordinates match score is {match_score}%, below the required 80% threshold. You are restricted from opening the camera and this action has been flagged."
        }), 403
    else:
        # VERIFIED >= 80%: ALLOW CAMERA ACCESS
        unflag_user(login_id)
        log_audit_event(
            login_id,
            "CAMERA_ACCESS_VERIFIED",
            distance_score=round(match_score / 100.0, 3),
            ip_address=client_ip
        )
        return jsonify({
            "success": True,
            "allowed": True,
            "restricted": False,
            "flagged": False,
            "match_score": match_score,
            "threshold": 80.0,
            "distance_km": eval_result.get("distance_km"),
            "subscores": eval_result.get("subscores"),
            "message": f"Digital fingerprint and location verified with {match_score}% confidence (>= 80% required). Camera unlocked for geo-tagged capture."
        }), 200

@app.route("/api/geo/capture-photo", methods=["POST"])
def capture_geotag_photo():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_session_token(token)
    if not payload:
        return jsonify({"success": False, "message": "Unauthorized."}), 401

    login_id = payload["login_id"]
    user = get_user_by_login_id(login_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    data = request.get_json() or {}
    image_b64 = data.get("image")
    geo_data = data.get("geo_data") or {}
    fingerprint_data = data.get("fingerprint_data") or {}

    if not image_b64:
        return jsonify({"success": False, "message": "No image data provided."}), 400

    # Recompute match_score server-side rather than trusting the client-supplied value,
    # which could otherwise be forged to bypass the geo/fingerprint check entirely.
    client_ip = get_client_ip()
    if not fingerprint_data.get("network"):
        fingerprint_data["network"] = {}
    if not fingerprint_data["network"].get("ip"):
        fingerprint_data["network"]["ip"] = client_ip

    reg_fp_raw = user.get("digital_fingerprint")
    reg_fp = {}
    if reg_fp_raw:
        try:
            reg_fp = json.loads(reg_fp_raw)
        except Exception:
            reg_fp = {}

    reg_baseline = {
        "latitude": user.get("geo_latitude"),
        "longitude": user.get("geo_longitude"),
        "accuracy": user.get("geo_accuracy"),
        "network": reg_fp.get("network") or {},
        "hardware": reg_fp.get("hardware") or {}
    }
    current_data = {
        "latitude": geo_data.get("latitude"),
        "longitude": geo_data.get("longitude"),
        "accuracy": geo_data.get("accuracy"),
        "network": fingerprint_data.get("network") or {},
        "hardware": fingerprint_data.get("hardware") or {}
    }
    eval_result = evaluate_geo_fingerprint_match(reg_baseline, current_data)
    match_score = eval_result["score"]

    if geo_data.get("isp_mismatch"):
        flag_user(login_id, f"GPS/ISP location mismatch at capture time ({geo_data.get('isp_distance_km')} km divergence).")
        log_audit_event(login_id, "GEOTAG_ISP_MISMATCH_FLAGGED", distance_score=round(match_score / 100.0, 3), ip_address=client_ip)
        return jsonify({"success": False, "message": "Geo-tag capture rejected: GPS reading does not match verified network location. This attempt has been flagged."}), 403

    if match_score < 80.0:
        flag_user(login_id, f"Digital Fingerprint Mismatch at capture: {match_score}% (< 80% required)")
        log_audit_event(login_id, "GEOTAG_CAPTURE_REJECTED_MISMATCH", distance_score=round(match_score / 100.0, 3), ip_address=client_ip)
        return jsonify({"success": False, "message": "Geo-tag capture rejected: Confidence is below required 80% threshold."}), 403

    try:
        raw_img = decode_base64_image(image_b64)
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid image format: {str(e)}"}), 400

    # High-tech HUD Watermark with Location Name & Coordinates
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    lat_val = float(geo_data.get("latitude") or 0.0)
    lon_val = float(geo_data.get("longitude") or 0.0)
    acc_val = float(geo_data.get("accuracy") or 5.0)
    loc_name = (
        geo_data.get("location_name")
        or geo_data.get("address")
        or user.get("geo_address")
        or reverse_geocode(lat_val, lon_val)
        or f"Sector: {lat_val:.4f}, {lon_val:.4f}"
    )
    addr_val = f"{loc_name} (GPS: {lat_val:.5f}, {lon_val:.5f})"

    geotag_info = {
        "latitude": lat_val,
        "longitude": lon_val,
        "accuracy": acc_val,
        "location_name": loc_name,
        "address": addr_val,
        "full_name": user["full_name"],
        "login_id": login_id,
        "match_score": match_score,
        "fingerprint_hash": fingerprint_data.get("device_hash") or user.get("device_hash") or "FP-VAULT-88",
        "timestamp": timestamp_str
    }
    
    watermarked_img = apply_geotag_watermark(raw_img, geotag_info)

    # Save to disk
    file_id = f"geotag_{login_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.jpg"
    file_path = os.path.join(GEOTAG_DIR, file_id)
    cv2.imwrite(file_path, watermarked_img)

    # Save to database
    capture_id = save_geo_capture(
        login_id=login_id,
        image_path=file_id,
        latitude=lat_val,
        longitude=lon_val,
        accuracy=acc_val,
        address=loc_name,
        match_score=match_score,
        fingerprint_hash=geotag_info["fingerprint_hash"]
    )

    log_audit_event(login_id, "GEOTAG_PHOTO_CAPTURED", distance_score=round(match_score / 100.0, 3), ip_address=get_client_ip())

    return jsonify({
        "success": True,
        "capture_id": capture_id,
        "image_url": f"/api/geo/photo/{file_id}",
        "match_score": match_score,
        "timestamp": timestamp_str,
        "message": "Geo-tagged photograph securely captured, watermarked, and archived."
    })

@app.route("/api/geo/photo/<filename>")
def get_geotag_photo(filename):
    safe_name = os.path.basename(filename)
    photo_path = os.path.join(GEOTAG_DIR, safe_name)
    if os.path.exists(photo_path):
        return send_file(photo_path, mimetype="image/jpeg")
    return jsonify({"success": False, "message": "Photo not found."}), 404

@app.route("/api/geo/captures", methods=["GET"])
def get_geotag_captures():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_session_token(token)
    if not payload:
        return jsonify({"success": False, "message": "Unauthorized."}), 401

    login_id = payload["login_id"]
    captures = get_user_geo_captures(login_id, limit=20)
    for c in captures:
        c["image_url"] = f"/api/geo/photo/{c['image_path']}"

    return jsonify({
        "success": True,
        "captures": captures
    })

@app.route("/api/geo/ip-lookup", methods=["GET"])
def api_geo_ip_lookup():
    client_ip = get_client_ip()
    
    # If user is authenticated, check their registered baseline first
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if token:
        payload = verify_session_token(token)
        if payload:
            user = get_user_by_login_id(payload.get("login_id"))
            if user and user.get("geo_latitude") is not None:
                return jsonify({
                    "success": True,
                    "latitude": user.get("geo_latitude"),
                    "longitude": user.get("geo_longitude"),
                    "accuracy": user.get("geo_accuracy") or 200.0,
                    "city": user.get("geo_address") or "Registered Baseline Sector",
                    "source": "REGISTERED_BASELINE",
                    "ip": client_ip
                })
    
    # Otherwise perform real-time public IP lookup
    geo = lookup_ip_geolocation(client_ip)
    if geo:
        city_str = geo["city"]
        if geo.get("region") and geo["region"] not in city_str:
            city_str = f"{city_str}, {geo['region']}"
        return jsonify({
            "success": True,
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "accuracy": geo["accuracy"],
            "city": city_str,
            "source": "PUBLIC_IP_RESOLVER",
            "ip": client_ip
        })
    
    # Fallback to general coordinates
    return jsonify({
        "success": True,
        "latitude": 22.5726,
        "longitude": 88.3639,
        "accuracy": 1500.0,
        "city": "Regional Gateway Sector",
        "source": "DEFAULT_GATEWAY",
        "ip": client_ip
    })

@app.route("/api/geo/calibrate", methods=["POST"])
def calibrate_geo_baseline():
    """
    Calibrate or fix user registered geographic baseline
    (e.g., when laptop Wi-Fi BSSID incorrectly points to another state like Andhra Pradesh instead of Durgapur, West Bengal).
    """
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    payload = verify_jwt_token(token)
    if not payload:
        return jsonify({"success": False, "message": "Authentication required"}), 401
    
    login_id = payload.get("login_id")
    data = request.get_json() or {}
    lat = data.get("latitude")
    lon = data.get("longitude")
    loc_name = data.get("location_name") or data.get("address")
    accuracy = float(data.get("accuracy") or 600.0)

    if lat is None or lon is None:
        # Detect from real ISP
        client_ip = get_client_ip()
        geo = lookup_ip_geolocation(client_ip)
        if geo:
            lat = geo["latitude"]
            lon = geo["longitude"]
            loc_name = geo["city"]
        else:
            lat = 23.5158
            lon = 87.3080
            loc_name = "Durgapur, West Bengal, India"
    
    if not loc_name:
        loc_name = reverse_geocode(lat, lon) or f"Calibrated Sector ({lat:.4f}°, {lon:.4f}°)"

    update_user_fingerprint_baseline(
        login_id,
        geo_data={"latitude": lat, "longitude": lon, "accuracy": accuracy, "address": loc_name}
    )
    return jsonify({
        "success": True,
        "message": f"Location baseline calibrated to {loc_name}",
        "latitude": lat,
        "longitude": lon,
        "location_name": loc_name
    })

@app.route("/api/avatar/<login_id>")
def get_avatar(login_id):
    avatar_path = os.path.join(AVATARS_DIR, f"{login_id}.jpg")
    if os.path.exists(avatar_path):
        return send_file(avatar_path, mimetype="image/jpeg")
    return send_file(os.path.join(BASE_DIR, "static", "img", "default_avatar.png"), mimetype="image/png")

# --- Progressive Web App (PWA) & Mobile Routes ---

@app.route("/manifest.json")
def pwa_manifest():
    return send_file(os.path.join(BASE_DIR, "static", "manifest.json"), mimetype="application/manifest+json")

@app.route("/sw.js")
def pwa_service_worker():
    response = make_response(send_file(os.path.join(BASE_DIR, "static", "sw.js"), mimetype="application/javascript"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response

@app.route("/api/mobile/info", methods=["GET"])
def mobile_info():
    lan_ip = get_lan_ip()
    port = request.environ.get("SERVER_PORT", 5000)
    scheme = "https" if request.is_secure else "http"
    return jsonify({
        "success": True,
        "lan_ip": lan_ip,
        "port": port,
        "scheme": scheme,
        "mobile_url": f"{scheme}://{lan_ip}:{port}",
        "desktop_url": f"{scheme}://127.0.0.1:{port}"
    })

@app.route("/api/mobile/qr", methods=["GET"])
def mobile_qr():
    try:
        import qrcode
        from io import BytesIO
        lan_ip = get_lan_ip()
        port = request.environ.get("SERVER_PORT", 5000)
        scheme = "https" if request.is_secure else "http"
        mobile_url = f"{scheme}://{lan_ip}:{port}"
        
        qr = qrcode.QRCode(box_size=7, border=2)
        qr.add_data(mobile_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#00f2fe", back_color="#070913")
        buf = BytesIO()
        img.save(buf)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FaceVault Biometric 2FA Engine")
    parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with self-signed SSL certificate for mobile camera access")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (0.0.0.0 enables mobile Wi-Fi access)")
    args = parser.parse_args()

    lan_ip = get_lan_ip()
    ssl_context = None

    if args.ssl:
        cert_path, key_path = ensure_ssl_certificates(DATA_DIR)
        ssl_context = (cert_path, key_path)
        protocol = "https"
    else:
        protocol = "http"

    print("==================================================================")
    print("   FaceVault Biometric 2FA Security Engine (Mobile & Web Ready)  ")
    print("==================================================================")
    print(f"  * Local PC URL:   {protocol}://127.0.0.1:{args.port}")
    if lan_ip != "127.0.0.1":
        print(f"  * Mobile Wi-Fi:   {protocol}://{lan_ip}:{args.port}")
    print(f"  * PWA App:        Installable on Android & iOS Home Screens")
    if args.ssl:
        print("  * HTTPS Mode:     ACTIVE (Mobile webcam & PWA fully enabled)")
    else:
        print("  * Mobile Tip:     Use --ssl mode to enable phone camera access")
    print("==================================================================")

    app.run(host=args.host, port=args.port, ssl_context=ssl_context, debug=False)

