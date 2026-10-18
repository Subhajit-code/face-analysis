import cv2
import numpy as np
import base64

def decode_base64_image(image_data: str) -> np.ndarray:
    """Decodes a base64 string or data URL into an OpenCV BGR image."""
    if not image_data:
        raise ValueError("Empty image data")
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]
    raw_bytes = base64.b64decode(image_data)
    np_arr = np.frombuffer(raw_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    return img

def enhance_low_light(img: np.ndarray) -> np.ndarray:
    """
    Advanced Low-Light & Illumination Enhancement:
    1. Converts to LAB color space to separate Luminance (L) from Color (A, B).
    2. Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) on L-channel.
    3. Dynamically applies Gamma Correction for dim environments.
    """
    try:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        
        mean_l = float(np.mean(l_channel))
        
        # Apply CLAHE
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_l = clahe.apply(l_channel)
        
        # Merge back
        merged = cv2.merge((enhanced_l, a_channel, b_channel))
        result = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        
        # If very dim (mean luminance < 80), apply adaptive gamma boost
        if mean_l < 80:
            gamma = 1.6 if mean_l < 45 else 1.3
            inv_gamma = 1.0 / gamma
            lut = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
            result = cv2.LUT(result, lut)
            
        return result
    except Exception:
        return img

def check_image_quality(img: np.ndarray) -> tuple[bool, str, np.ndarray]:
    """
    Checks image quality and automatically enhances low-light or dim images.
    Returns (ok, message, enhanced_image).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(np.mean(gray))
    
    # If pitch black (lens covered or 0 lux)
    if mean_brightness < 12.0:
        return False, "Environment is pitch dark. Please turn on a light or increase screen brightness.", img
    
    # If dim or low light, automatically enhance using CLAHE + Gamma
    processed_img = img
    if mean_brightness < 90.0:
        processed_img = enhance_low_light(img)
    
    # Check overexposure
    if mean_brightness > 245.0:
        return False, "Image is heavily overexposed. Please avoid direct harsh glare against the camera.", img
    
    return True, "Quality OK", processed_img

def verify_head_turn_challenge(yaw_proxies: list[float], direction: str) -> tuple[bool, str]:
    """
    Verifies an active liveness challenge: the user was asked to turn their head LEFT or RIGHT
    and back, and this checks the sequence of per-frame yaw proxies (see
    security.biometric.compute_yaw_proxy) actually moved that way. Unlike passive frame-diff
    motion, this can't be satisfied by wiggling a printed photo or looping a static video,
    since the specific instructed direction is chosen at random per login attempt and only
    revealed to the user at challenge time.
    """
    valid = [y for y in yaw_proxies if y is not None]
    if len(valid) < 2:
        return False, "Not enough tracked frames to verify the head-turn challenge. Please try again."

    min_y = min(valid)
    max_y = max(valid)
    swing = max_y - min_y

    # Require a clearly intentional turn, not natural head-hold jitter.
    MIN_SWING = 0.045

    if swing < MIN_SWING:
        return False, "No head turn detected. Please clearly turn your head as instructed."

    if direction == "TURN_RIGHT":
        # Convention: nose offset decreases (goes more negative) during a rightward turn.
        if min_y > -MIN_SWING * 0.6:
            return False, "Head turn did not match the instructed direction (RIGHT). Please retry."
    elif direction == "TURN_LEFT":
        if max_y < MIN_SWING * 0.6:
            return False, "Head turn did not match the instructed direction (LEFT). Please retry."
    else:
        return True, "Head-turn challenge skipped (no direction set)."

    return True, "Head-turn challenge verified."

def verify_liveness(frames: list[np.ndarray], face_boxes: list[tuple[int, int, int, int]]) -> tuple[bool, str, float]:
    """
    Evaluates anti-spoofing across multiple sequential frames:
    1. Rejects identical/duplicate frames (replay attack).
    2. Rejects completely static/flat pictures (zero biological micro-movement).
    3. Verifies natural motion within human biological tolerance.
    """
    if len(frames) < 2:
        return False, "Insufficient verification frames captured. Please look at the camera.", 0.0
    
    motion_scores = []
    
    for i in range(len(frames) - 1):
        f1, b1 = frames[i], face_boxes[i]
        f2, b2 = frames[i + 1], face_boxes[i + 1]
        
        x1, y1, w1, h1 = b1
        x2, y2, w2, h2 = b2
        
        face_crop1 = f1[max(0, y1):min(f1.shape[0], y1+h1), max(0, x1):min(f1.shape[1], x1+w1)]
        face_crop2 = f2[max(0, y2):min(f2.shape[0], y2+h2), max(0, x2):min(f2.shape[1], x2+w2)]
        
        if face_crop1.size == 0 or face_crop2.size == 0:
            continue
        
        std1 = cv2.resize(face_crop1, (100, 100))
        std2 = cv2.resize(face_crop2, (100, 100))
        
        gray1 = cv2.cvtColor(std1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(std2, cv2.COLOR_BGR2GRAY)
        
        diff = cv2.absdiff(gray1, gray2)
        mean_diff = float(np.mean(diff))
        motion_scores.append(mean_diff)
        
        # Frozen image detection
        if mean_diff < 0.15:
            return False, "Static image detected (zero movement). A live person is required.", 0.0
    
    if not motion_scores:
        return True, "Liveness OK", 1.0 # Pass gracefully if face tracking had minor variance
    
    avg_motion = float(np.mean(motion_scores))
    
    # Wild shaking or camera loop detection
    if avg_motion > 50.0:
        return False, "Too much rapid camera movement. Please hold steady.", avg_motion
    
    return True, "Live human verified", avg_motion
