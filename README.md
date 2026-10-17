# Biometric Vault - Tamper-Proof Multi-User Face Recognition System

A high-security, multi-user authentication platform that fuses traditional credential verification (User ID & Password) with deep-learning facial biometrics (128-dimensional embedding vectors) and active anti-spoofing liveness checks.

---

## Key Features

1. **2-Factor Authentication:**
   - **Factor 1:** Salted PBKDF2-HMAC-SHA256 password verification.
   - **Factor 2:** Server-side facial biometric verification powered by OpenCV SFace and YuNet deep neural networks.
2. **Fool-Proof Zero-Trust Architecture:**
   - **Zero Client Trust:** Authentication decisions are calculated strictly on the backend. Modifying client JavaScript or DevTools cannot bypass authentication.
   - **AES-256-GCM Biometric Vault:** Facial vectors are encrypted at rest with hardware-grade AES-256-GCM.
   - **Anti-Replay Protection:** Every camera scan requires a dynamic single-use 60-second cryptographic challenge nonce.
   - **Liveness Detection & Anti-Spoofing:** Rejects static smartphone screens and printed photos.
   - **Brute Force Lockout:** 5 consecutive failed attempts trigger a 15-minute account lockout.
   - **Zero Exposed Network Ports:** Uses in-process SQLite (`auth_vault.db`), eliminating network port vulnerabilities.
3. **Cyber-HUD Interface:**
   - Real-time video preview with futuristic holographic face targeting oval and corner HUD brackets.
   - Animated laser scan line with Web Audio API sound effects.
   - Celebratory Good Notification modal upon match confirmation.
   - User Dashboard displaying session details, enrolled avatar, and immutable audit logs.

---

## Quick Start (Windows)

### Option 1: Double-Click Launcher
Simply double-click **`run.bat`** in the project folder. It will launch the backend server and automatically open `http://127.0.0.1:5000` in your web browser.

### Option 2: Command Line
```powershell
# Navigate to the project directory
cd "c:\Users\subha\Desktop\own\facial recognisation"

# Start the application
.\venv\Scripts\python.exe app.py
```
Open **`http://127.0.0.1:5000`** in your browser (Google Chrome, Microsoft Edge, or Firefox).

---

## User Guide

### 1. Enrolling a New User
1. Click the **Enroll New User** tab.
2. Enter your desired **Login ID** (e.g. `subhash_01`), **Full Name**, and **Password** (min 6 chars).
3. Look into the camera viewfinder and click **Capture Face**.
4. Confirm the preview snapshot, then click **Register & Save Biometrics**.

### 2. Signing In (2-Factor Biometric Verification)
1. In the **Secure Sign In** tab, enter your registered **Login ID** and **Password**.
2. Click **Proceed to Biometric Scan**.
3. When the camera HUD appears, align your face in the holographic oval.
4. Click **Capture & Verify Face**:
   - The system performs a countdown, triggers a laser scan sweep, and samples consecutive frames.
   - **If Match Confirmed:** Plays a celebratory chime, displays the **Biometric Match Confirmed** notification card with your match confidence percentage, and unlocks your private **User Dashboard**.
   - **If Mismatch:** Plays a refusal tone, blocks entry, logs the incident, and decrements remaining attempts.

---

## Directory Layout
```
facial recognisation/
├── app.py                     # Main application server & API controller
├── run.bat                    # 1-Click Windows launcher
├── requirements.txt           # Python dependencies
├── security/
│   ├── crypto.py              # AES-256-GCM encryption & password hashing
│   ├── biometric.py           # YuNet face detector & SFace 128-d recognizer
│   └── liveness.py            # Anti-spoofing and micro-motion analyzer
├── models/
│   ├── database.py            # SQLite schema, rate limiting & nonces
│   └── weights/               # Deep learning ONNX model weights (YuNet & SFace)
├── static/
│   ├── css/style.css          # Futuristic dark-mode cyber HUD styling
│   ├── js/
│   │   ├── app.js             # 2-step auth controller & state machine
│   │   ├── camera.js          # Hardware webcam controller & burst sampling
│   │   └── audio.js           # Web Audio API sound synthesizer
│   └── img/                   # Default avatars and static assets
├── templates/
│   └── index.html             # Single-page biometric web application
└── data/                      # Local encrypted SQLite vault & user avatars
```
