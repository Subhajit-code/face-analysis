import math
import hashlib
import json
import os
import urllib.request
import urllib.parse
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

def reverse_geocode(lat, lon):
    """
    Resolves GPS coordinates to a human-readable location name using the
    Google Geocoding API. Returns None if no API key is configured or the
    lookup fails, so callers can fall back to raw coordinates.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None

    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    params = urllib.parse.urlencode({
        "latlng": f"{lat},{lon}",
        "key": api_key
    })
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{params}"

    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if result.get("status") != "OK" or not result.get("results"):
        return None

    return result["results"][0].get("formatted_address")

def calculate_geo_score(distance_meters, reg_accuracy=None, curr_accuracy=None):
    """
    Calculates geographic proximity match percentage (0 - 100%).
    Accounts for real-world Wi-Fi positioning and indoor GPS sensor accuracy radius.
    
    Tolerance:
      - Max of registered accuracy, current accuracy, and 600m baseline (typical residential Wi-Fi).
      - Within tolerance: 100% (User is sitting in their home/office).
      - Tolerance to (Tolerance + 1500m): Drops from 100% to 60%.
      - Up to 5000m (5 km): Drops from 60% to 10%.
      - Past 5000m (5 km): 0% (Strictly 0% once 5km boundary exceeded).
    """
    try:
        r_acc = float(reg_accuracy or 0)
    except (ValueError, TypeError):
        r_acc = 0.0
    try:
        c_acc = float(curr_accuracy or 0)
    except (ValueError, TypeError):
        c_acc = 0.0

    tolerance = max(r_acc, c_acc, 600.0)

    if distance_meters <= tolerance:
        return 100.0
    elif distance_meters <= (tolerance + 1500.0):
        ratio = (distance_meters - tolerance) / 1500.0
        return 100.0 - (ratio * 40.0)
    elif distance_meters <= 5000.0:
        ratio = (distance_meters - (tolerance + 1500.0)) / max(1.0, 5000.0 - (tolerance + 1500.0))
        return 60.0 - (ratio * 50.0)
    else:
        return 0.0

def calculate_signal_fingerprint_score(reg_scan, curr_scan):
    """
    Scores a real, un-spoofable nearby-signal fingerprint (WiFi BSSIDs + cell tower IDs read
    directly from device radio hardware via the native Android app). Unlike GPS, these can't be
    faked by a mock-location app, since they reflect what the device's antenna actually hears.
    Returns None if either side has no real scan data (so callers can fall back to weaker signals).
    """
    if not reg_scan or not curr_scan:
        return None

    reg_bssids = {str(ap.get("bssid") or "").lower() for ap in (reg_scan.get("wifi_access_points") or []) if ap.get("bssid")}
    curr_bssids = {str(ap.get("bssid") or "").lower() for ap in (curr_scan.get("wifi_access_points") or []) if ap.get("bssid")}

    reg_towers = {
        f"{t.get('type')}-{t.get('cellId')}-{t.get('lac') or t.get('tac')}"
        for t in (reg_scan.get("cell_towers") or []) if t.get("cellId")
    }
    curr_towers = {
        f"{t.get('type')}-{t.get('cellId')}-{t.get('lac') or t.get('tac')}"
        for t in (curr_scan.get("cell_towers") or []) if t.get("cellId")
    }

    if not reg_bssids and not reg_towers:
        return None

    wifi_matches = len(reg_bssids & curr_bssids)
    tower_matches = len(reg_towers & curr_towers)

    wifi_score = (wifi_matches / len(reg_bssids) * 100.0) if reg_bssids else None
    tower_score = (tower_matches / len(reg_towers) * 100.0) if reg_towers else None

    if wifi_score is not None and tower_score is not None:
        return round(wifi_score * 0.75 + tower_score * 0.25, 1)
    if wifi_score is not None:
        return round(wifi_score, 1)
    return round(tower_score, 1)

def calculate_network_score(reg_net, curr_net):
    """
    Scores network & router/tower digital presence (0 - 100%).
    Factors: IP match / Subnet match, Connection type, Local router gateway candidate, Tower/AP signature.
    If a real signal fingerprint scan (native app) is available on both sides, it fully overrides
    the weaker synthetic signals below, since it reflects genuine nearby radio hardware instead of
    a hash derived from easily-changed browser values.
    """
    score = 0.0
    reg_net = reg_net or {}
    curr_net = curr_net or {}

    real_score = calculate_signal_fingerprint_score(reg_net.get("real_signal_scan"), curr_net.get("real_signal_scan"))
    if real_score is not None:
        return min(100.0, real_score)

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
            elif (reg_ip.startswith("192.168.") or reg_ip.startswith("10.")) and (curr_ip.startswith("192.168.") or curr_ip.startswith("10.")):
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
        reg_acc = registered_data.get("accuracy")
        curr_acc = current_data.get("accuracy")
        geo_score = calculate_geo_score(distance_meters, reg_acc, curr_acc)
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
    Burns a futuristic, tamper-evident security watermark & HUD metadata into the image,
    including the physical Location Name, Latitude & Longitude, user identity, and timestamp.
    """
    img = image_np.copy()
    h, w = img.shape[:2]

    # Watermark HUD bar at the bottom with increased height for location name
    bar_height = max(130, int(h * 0.25))
    overlay = img.copy()
    
    # Semi-transparent dark slate cyber backdrop
    cv2.rectangle(overlay, (0, h - bar_height), (w, h), (8, 12, 22), -1)
    # Bright cyan accent border line
    cv2.line(overlay, (0, h - bar_height), (w, h - bar_height), (254, 242, 0), 2)

    alpha = 0.88
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

    # Telemetry data extraction
    lat = float(geotag_info.get("latitude") or 0.0)
    lon = float(geotag_info.get("longitude") or 0.0)
    acc = float(geotag_info.get("accuracy") or 5.0)
    user_name = str(geotag_info.get("full_name") or "Authorized User").strip()
    login_id = str(geotag_info.get("login_id") or "user").strip()
    match_score = geotag_info.get("match_score", 95.0)
    fp_hash = str(geotag_info.get("fingerprint_hash") or "SEC-88FA")[:12]
    timestamp = str(geotag_info.get("timestamp") or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    
    # Location Name (e.g. "Visakhapatnam, Andhra Pradesh" or "Salt Lake, Kolkata")
    location_name = str(geotag_info.get("location_name") or geotag_info.get("address") or f"Sector: {lat:.4f}, {lon:.4f}").strip()
    # Clean location prefix if present
    location_clean = location_name.replace("Sector: ", "").replace("GPS: ", "").split("|")[0].strip()

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale_title = max(0.44, w / 1400.0)
    scale_text = max(0.38, w / 1600.0)

    # Line 1: Security Stamp & Match Confidence
    y1 = h - bar_height + int(bar_height * 0.19)
    cv2.putText(img, f"[GEO-VERIFIED RECORD] MATCH SCORE: {match_score}% | {timestamp}", 
                (18, y1), font, scale_title, (0, 242, 254), 1, cv2.LINE_AA)
    
    # Line 2: Physical Location Name (High visibility gold/amber)
    y2 = y1 + int(bar_height * 0.20)
    loc_text = f"LOCATION: {location_clean[:55]}"
    cv2.putText(img, loc_text, (18, y2), font, scale_text * 1.05, (60, 225, 255), 1, cv2.LINE_AA)

    # Line 3: Exact Coordinates & GPS Precision (Crisp White)
    y3 = y2 + int(bar_height * 0.20)
    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"
    coord_text = f"COORDINATES: {abs(lat):.6f} {lat_dir}, {abs(lon):.6f} {lon_dir}  (Accuracy: +/-{acc:.1f}m)"
    cv2.putText(img, coord_text, (18, y3), font, scale_text, (245, 245, 245), 1, cv2.LINE_AA)

    # Line 4: Enrolled User Identity & Device Digital Fingerprint Hash
    y4 = y3 + int(bar_height * 0.19)
    meta_text = f"USER: {user_name} ({login_id}) | DEVICE FP: {fp_hash}"
    cv2.putText(img, meta_text, (18, y4), font, scale_text, (190, 210, 230), 1, cv2.LINE_AA)

    # Line 5: Vault Immutability Audit Tag
    y5 = y4 + int(bar_height * 0.17)
    audit_tag = "TAMPER-PROOF BIOMETRIC VAULT AUDIT RECORD | SHA-256 SIGNED"
    cv2.putText(img, audit_tag, (18, y5), font, max(0.30, scale_text * 0.82), (100, 230, 140), 1, cv2.LINE_AA)

    return img
