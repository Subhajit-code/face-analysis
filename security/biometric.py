import os
import cv2
import numpy as np
from security.liveness import enhance_low_light

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "weights")
YUNET_PATH = os.path.join(MODELS_DIR, "face_detection_yunet.onnx")
SFACE_PATH = os.path.join(MODELS_DIR, "face_recognition_sface.onnx")

_detector = None
_recognizer = None

def get_face_detector(width=320, height=320):
    global _detector
    if _detector is None:
        if not os.path.exists(YUNET_PATH):
            raise FileNotFoundError(f"YuNet model not found at {YUNET_PATH}")
        _detector = cv2.FaceDetectorYN.create(
            YUNET_PATH,
            "",
            (width, height),
            score_threshold=0.55,
            nms_threshold=0.3,
            top_k=5000
        )
    else:
        _detector.setInputSize((width, height))
    return _detector

def get_face_recognizer():
    global _recognizer
    if _recognizer is None:
        if not os.path.exists(SFACE_PATH):
            raise FileNotFoundError(f"SFace model not found at {SFACE_PATH}")
        _recognizer = cv2.FaceRecognizerSF.create(SFACE_PATH, "")
    return _recognizer

def detect_faces(img: np.ndarray) -> tuple[int, list]:
    """
    Detects faces with built-in Low-Light Auto-Boost:
    1. First tries detection on the original frame.
    2. If no face is found (e.g. in low light or shadows), applies CLAHE + Gamma enhancement and retries.
    """
    h, w = img.shape[:2]
    detector = get_face_detector(w, h)
    _, faces = detector.detect(img)
    
    # Filter faces with confidence >= 0.65
    valid_faces = [f for f in faces if f[-1] >= 0.65] if (faces is not None and len(faces) > 0) else []
    
    # Low-light fallback
    if len(valid_faces) == 0:
        enhanced = enhance_low_light(img)
        _, faces2 = detector.detect(enhanced)
        if faces2 is not None and len(faces2) > 0:
            valid_faces = [f for f in faces2 if f[-1] >= 0.60]
            
    return len(valid_faces), valid_faces

def compute_yaw_proxy(face) -> float:
    """
    Estimates head yaw (left/right turn) from YuNet's 5-point landmarks without a separate
    pose-estimation model. YuNet's output per face is
    [x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score]
    (right eye, left eye, nose tip, right mouth corner, left mouth corner).
    When the head is frontal, the nose tip sits roughly at the eye midpoint's x-coordinate.
    Turning the head shifts the nose tip off-center relative to the eyes; the direction and
    magnitude of that offset (normalized by face width) is a cheap, model-free yaw proxy used
    to verify an active head-turn liveness challenge.
    """
    face_w = float(face[2]) or 1.0
    eye_mid_x = (float(face[4]) + float(face[6])) / 2.0
    nose_x = float(face[8])
    return (nose_x - eye_mid_x) / face_w

def compute_face_quality(img: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[bool, str, float]:
    """
    Gates out low-quality frames before they reach recognition/liveness: faces that are too
    small (far from camera / low-res crop) or too blurry (motion blur, bad focus, or a flat
    printed-photo texture) are unreliable for both matching and anti-spoof checks.
    Returns: (ok, message, laplacian_variance)
    """
    x, y, w, h = bbox
    if w < 80 or h < 80:
        return False, "Face is too small/far from the camera. Please move closer.", 0.0

    crop = img[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        return False, "Face crop out of bounds.", 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Real skin has fine micro-texture; a flat printed photo or a low-res screen replay tends
    # to have unnaturally low Laplacian variance once blur from camera motion is accounted for.
    if lap_var < 15.0:
        return False, "Image is too blurry or unnaturally flat (possible photo/print spoof). Please use a live camera feed in good focus.", lap_var

    return True, "OK", lap_var

def extract_face_data(img: np.ndarray, face) -> tuple[list[float], tuple[int, int, int, int], np.ndarray]:
    """
    Aligns, crops, and extracts unit-normalized 128-d biometric embedding for a given face.
    Returns: (embedding_list, (x, y, w, h), aligned_crop_img)
    """
    recognizer = get_face_recognizer()
    
    x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
    aligned_face = recognizer.alignCrop(img, face)
    
    # Feature extraction
    feature = recognizer.feature(aligned_face)
    raw_desc = feature[0]
    
    # Unit normalization so cosine similarity and Euclidean distance are mathematically exact
    norm = np.linalg.norm(raw_desc)
    if norm > 0:
        normalized_desc = (raw_desc / norm).tolist()
    else:
        normalized_desc = raw_desc.tolist()
        
    return normalized_desc, (x, y, w, h), aligned_face

def compare_faces(
    desc1: list[float],
    desc2: list[float],
    min_confidence: int = 80,              # User specification: ONLY grant entry if confidence is at least 80%
    cosine_threshold: float = None,
    **kwargs
) -> tuple[bool, float, float, int, bool]:
    """
    Compares two unit-normalized 128-d face descriptors:
    - Calculates mathematically calibrated 0-100% confidence.
    - STRICT SECURITY RULE: Entry is ONLY granted if match confidence >= 80%.
    - If confidence < 80%, access is denied.
    
    Returns: (is_match, cosine_sim, l2_dist, confidence_percentage, is_impersonation_suspect)
    """
    v1 = np.array(desc1, dtype=np.float32)
    v2 = np.array(desc2, dtype=np.float32)
    
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    
    if norm1 == 0 or norm2 == 0:
        return False, 0.0, 99.0, 0, False
    
    # Ensure unit normalization
    v1 = v1 / norm1
    v2 = v2 / norm2
    
    # 1. Cosine Similarity (dot product of unit vectors)
    cosine_sim = float(np.dot(v1, v2))
    
    # 2. L2 Euclidean Distance
    l2_dist = float(np.linalg.norm(v1 - v2))
    
    # Convert Cosine Similarity to Intuitive 0-100% Confidence Score
    if cosine_sim <= 0.0:
        conf_pct = 0
    elif cosine_sim < 0.25:
        # Different people / strangers: 0% to 35%
        conf_pct = int((cosine_sim / 0.25) * 35)
    elif cosine_sim < 0.48:
        # Mild / lookalike / weak angle: 36% to 79% (REJECTED: below 80%)
        conf_pct = int(36 + ((cosine_sim - 0.25) / 0.23) * 43)
    else:
        # Strong match: 0.48 to 0.92+ -> 80% to 99% (MEETS 80% REQUIREMENT!)
        conf_pct = min(99, int(80 + ((cosine_sim - 0.48) / 0.44) * 19))
    
    # Strict 80% Rule: ONLY enter if confidence is >= 80%
    is_match = (conf_pct >= min_confidence)
    
    # Impostor attempt: if failed to reach 80%, but had mild resemblance (0.24 to 0.47)
    is_impersonation_suspect = (not is_match) and (cosine_sim >= 0.24)
    
    return is_match, cosine_sim, l2_dist, conf_pct, is_impersonation_suspect

def extract_single_face(img: np.ndarray) -> tuple[bool, str, list[float] | None, tuple[int, int, int, int] | None, np.ndarray | None]:
    """
    Validates single face with auto-enhancement for dim lighting.
    Returns: (ok, message, descriptor, bbox, aligned_crop)
    """
    face_count, faces = detect_faces(img)
    
    if face_count == 0:
        return False, "No face detected. Please face the camera directly.", None, None, None
    if face_count > 1:
        return False, f"Multiple faces detected ({face_count}). Only one person is allowed.", None, None, None
    
    descriptor, bbox, aligned_crop = extract_face_data(img, faces[0])
    return True, "Face extracted successfully", descriptor, bbox, aligned_crop
