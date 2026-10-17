import math
import hashlib
import json
import cv2
import numpy as np
from datetime import datetime

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Computes great-circle distance between two GPS coordinates in meters using Haversine formula.
    """
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return 999999.0

    R = 6371000.0  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return R * c

def calculate_geo_score(distance_meters):
    """
    Calculates geographic proximity match percentage (0 - 100%).
    <= 100m (Same building/office perimeter): 100%
    100m - 500m (Immediate vicinity): 90% -> 70%
    500m - 2km (Left premises, router range broken): 70% -> 30%
    2km - 5km (Different neighborhood/sector): 30% -> 5%
    > 5km (Completely outside sector): 0%
    """
    if distance_meters <= 100:
        return 100.0
    elif distance_meters <= 500:
        ratio = (distance_meters - 100) / 400.0
        return 100.0 - (ratio * 30.0)
    elif distance_meters <= 2000:
        ratio = (distance_meters - 500) / 1500.0
        return 70.0 - (ratio * 40.0)
    elif distance_meters <= 5000:
        ratio = (distance_meters - 2000) / 3000.0
        return 30.0 - (ratio * 25.0)
    else:
        return 0.0

def calculate_network_score(reg_net, curr_net):
    """
    Scores network & router/tower digital presence (0 - 100%).
    Factors: IP match / Subnet match, Connection type, Local router gateway candidate, Tower/AP signature.
    """
    score = 0.0
    reg_net = reg_net or {}
    curr_net = curr_net or {}

    reg_ip = str(reg_net.get("ip") or "").strip()
    curr_ip = str(curr_net.get("ip") or "").strip()

    # 1. Public IP / Subnet (40 pts)
    if reg_ip and curr_ip:
        if reg_ip == curr_ip:
            score += 40.0
        else:
            # Check /24 subnet (first 3 octets)
            r_parts = reg_ip.split(".")
            c_parts = curr_ip.split(".")
            if len(r_parts) == 4 and len(c_parts) == 4 and r_parts[:3] == c_parts[:3]:
                score += 30.0
            elif reg_ip in ("127.0.0.1", "localhost") or curr_ip in ("127.0.0.1", "localhost"):
                score += 35.0
            else:
                score += 5.0

    # 2. Connection Type (WiFi, 4G, 5G, ethernet) (20 pts)
    reg_type = str(reg_net.get("connection_type") or "").lower()
    curr_type = str(curr_net.get("connection_type") or "").lower()
    if reg_type and curr_type:
        if reg_type == curr_type:
            score += 20.0
        else:
            score += 5.0
    else:
        score += 15.0

    # 3. Local Gateway / WebRTC Router candidate (25 pts)
    reg_gw = str(reg_net.get("local_gateway") or "").strip()
    curr_gw = str(curr_net.get("local_gateway") or "").strip()
    if reg_gw and curr_gw:
        if reg_gw == curr_gw:
            score += 25.0
        else:
            score += 5.0
    else:
        score += 20.0

    # 4. Nearby Tower / Router BSSID Hash Signature (15 pts)
    reg_tower = str(reg_net.get("tower_signature") or "").strip()
    curr_tower = str(curr_net.get("tower_signature") or "").strip()
    if reg_tower and curr_tower:
        if reg_tower == curr_tower:
            score += 15.0
        else:
            score += 0.0
    else:
        score += 12.0

    return min(100.0, score)

def calculate_hardware_score(reg_hw, curr_hw):
    """
    Scores hardware device fingerprint traits (0 - 100%).
    Factors: Canvas hash, WebGL GPU renderer, AudioContext signature, Screen specs, Platform/CPU.
    """
    score = 0.0
    reg_hw = reg_hw or {}
    curr_hw = curr_hw or {}

    # 1. Canvas 2D Hash (35 pts)
    reg_canvas = str(reg_hw.get("canvas_hash") or "").strip()
    curr_canvas = str(curr_hw.get("canvas_hash") or "").strip()
    if reg_canvas and curr_canvas:
        if reg_canvas == curr_canvas:
            score += 35.0
    else:
        score += 25.0

    # 2. WebGL Renderer & Vendor (25 pts)
    reg_webgl = str(reg_hw.get("webgl_renderer") or "").strip().lower()
    curr_webgl = str(curr_hw.get("webgl_renderer") or "").strip().lower()
    if reg_webgl and curr_webgl:
        if reg_webgl == curr_webgl:
            score += 25.0
        else:
            score += 0.0
    else:
        score += 20.0

    # 3. AudioContext Acoustic Signature (15 pts)
    reg_audio = str(reg_hw.get("audio_hash") or "").strip()
    curr_audio = str(curr_hw.get("audio_hash") or "").strip()
    if reg_audio and curr_audio:
        if reg_audio == curr_audio:
            score += 15.0
    else:
        score += 12.0

    # 4. Screen Geometry & Pixel Ratio (10 pts)
    reg_screen = str(reg_hw.get("screen") or "").strip()
    curr_screen = str(curr_hw.get("screen") or "").strip()
    if reg_screen and curr_screen:
        if reg_screen == curr_screen:
            score += 10.0
        else:
            score += 2.0
    else:
        score += 8.0

    # 5. Platform & CPU Concurrency (10 pts)
    reg_plat = str(reg_hw.get("platform") or "").strip().lower()
    curr_plat = str(curr_hw.get("platform") or "").strip().lower()
    reg_cpu = str(reg_hw.get("cpu_cores") or "").strip()
    curr_cpu = str(curr_hw.get("cpu_cores") or "").strip()
    if reg_plat and curr_plat and reg_plat == curr_plat:
        score += 5.0
    if reg_cpu and curr_cpu and reg_cpu == curr_cpu:
        score += 5.0

    # 6. Timezone & Language (5 pts)
    reg_tz = str(reg_hw.get("timezone") or "").strip()
    curr_tz = str(curr_hw.get("timezone") or "").strip()
    if reg_tz and curr_tz and reg_tz == curr_tz:
        score += 5.0

    return min(100.0, score)

def evaluate_geo_fingerprint_match(registered_data, current_data):
    """
    Evaluates composite Geo-Digital Fingerprint Match against 80.0% threshold.
    Weights:
      - Geo Coordinate Proximity: 40%
      - Network, Router & Tower Environment: 30%
      - Hardware Device Fingerprint: 30%
    """
    reg_lat = registered_data.get("latitude")
    reg_lon = registered_data.get("longitude")
    curr_lat = current_data.get("latitude")
    curr_lon = current_data.get("longitude")

    # If coordinates are present
    if reg_lat is not None and reg_lon is not None and curr_lat is not None and curr_lon is not None:
        distance_meters = haversine_distance(reg_lat, reg_lon, curr_lat, curr_lon)
        geo_score = calculate_geo_score(distance_meters)
    else:
        distance_meters = 0.0
        geo_score = 90.0

    # Network / Router / Tower
    reg_net = registered_data.get("network") or {}
    curr_net = current_data.get("network") or {}
    network_score = calculate_network_score(reg_net, curr_net)

    # Hardware & Device Fingerprint
    reg_hw = registered_data.get("hardware") or {}
    curr_hw = current_data.get("hardware") or {}
    hardware_score = calculate_hardware_score(reg_hw, curr_hw)

    # Composite Weighted Total (0 - 100%)
    total_score = round(geo_score * 0.40 + network_score * 0.30 + hardware_score * 0.30, 1)
    
    # Strict 80% threshold rule
    is_match = total_score >= 80.0

    reasons = []
    if geo_score < 70.0:
        dist_km = round(distance_meters / 1000.0, 2)
        reasons.append(f"Geographic discrepancy: Location deviates by {dist_km} km from registered baseline.")
    if network_score < 60.0:
        reasons.append("Network variance: IP subnet, local gateway router, or tower signature mismatch.")
    if hardware_score < 60.0:
        reasons.append("Device variance: Hardware canvas/webgl digital fingerprint signature differs.")

    summary_msg = ""
    if is_match:
        summary_msg = f"Digital fingerprint and location verified with {total_score}% confidence (>= 80% required)."
    else:
        summary_msg = f"Digital fingerprint mismatch: Confidence score is {total_score}%, below the required 80% threshold. Camera restricted."

    return {
        "matched": is_match,
        "score": total_score,
        "threshold": 80.0,
        "distance_meters": round(distance_meters, 1),
        "distance_km": round(distance_meters / 1000.0, 2),
        "subscores": {
            "geo": round(geo_score, 1),
            "network": round(network_score, 1),
            "hardware": round(hardware_score, 1)
        },
        "reasons": reasons,
        "message": summary_msg
    }

def apply_geotag_watermark(image_np, geotag_info):
    """
    Burns a futuristic, tamper-evident security watermark & HUD metadata into the image.
    """
    img = image_np.copy()
    h, w = img.shape[:2]

    # Watermark HUD bar at the bottom
    bar_height = max(110, int(h * 0.22))
    overlay = img.copy()
    
    # Semi-transparent dark slate backdrop
    cv2.rectangle(overlay, (0, h - bar_height), (w, h), (10, 14, 25), -1)
    # Cyan accent line
    cv2.line(overlay, (0, h - bar_height), (w, h - bar_height), (254, 242, 0), 2)

    alpha = 0.85
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

    # Text telemetry
    lat = geotag_info.get("latitude", 0.0)
    lon = geotag_info.get("longitude", 0.0)
    acc = geotag_info.get("accuracy", 5.0)
    user_name = geotag_info.get("full_name", "Authorized User")
    login_id = geotag_info.get("login_id", "user")
    match_score = geotag_info.get("match_score", 95.0)
    fp_hash = geotag_info.get("fingerprint_hash", "SEC-88FA")[:12]
    timestamp = geotag_info.get("timestamp", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    address = geotag_info.get("address") or f"LAT: {lat:.6f}, LON: {lon:.6f}"

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale_title = max(0.45, w / 1400.0)
    scale_text = max(0.38, w / 1600.0)

    # Line 1: Security Stamp & Status
    y_start = h - bar_height + int(bar_height * 0.22)
    cv2.putText(img, f"[GEO-VERIFIED PHOTO] MATCH CONFIDENCE: {match_score}%", 
                (18, y_start), font, scale_title, (0, 242, 254), 1, cv2.LINE_AA)
    
    # Line 2: Coordinates & Accuracy
    y_line2 = y_start + int(bar_height * 0.24)
    coord_text = f"GPS: {lat:.6f} N, {lon:.6f} E (+/-{acc:.1f}m) | {address[:40]}"
    cv2.putText(img, coord_text, (18, y_line2), font, scale_text, (240, 240, 240), 1, cv2.LINE_AA)

    # Line 3: User ID & Timestamp
    y_line3 = y_line2 + int(bar_height * 0.24)
    meta_text = f"USER: {user_name} ({login_id}) | TIME: {timestamp}"
    cv2.putText(img, meta_text, (18, y_line3), font, scale_text, (180, 200, 220), 1, cv2.LINE_AA)

    # Line 4: Digital Fingerprint Hash Stamp
    y_line4 = y_line3 + int(bar_height * 0.22)
    fp_text = f"DIGITAL FP HASH: {fp_hash} | TAMPER-PROOF BIOMETRIC VAULT AUDIT RECORD"
    cv2.putText(img, fp_text, (18, y_line4), font, max(0.32, scale_text * 0.85), (100, 220, 140), 1, cv2.LINE_AA)

    return img
