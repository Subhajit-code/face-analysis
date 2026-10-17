/**
 * Biometric Vault - Main Application Controller
 */

// Configurable API Base URL (Supports Netlify Proxy or direct Render Backend URL)
const API_BASE = window.FACEVAULT_API_URL || localStorage.getItem("facevault_api_url") || "";

function getApiUrl(endpoint) {
    if (API_BASE && !endpoint.startsWith("http")) {
        return `${API_BASE.replace(/\/$/, "")}${endpoint}`;
    }
    return endpoint;
}

let currentLoginId = null;
let currentNonce = null;
let currentUserName = null;
let enrolledSnapshotData = null;
let sessionUser = null;

// --- DOM References ---
const loginView = document.getElementById("loginView");
const registerView = document.getElementById("registerView");
const dashboardView = document.getElementById("dashboardView");
const authTabs = document.getElementById("authTabs");

const loginStep1 = document.getElementById("loginStep1");
const loginStep2 = document.getElementById("loginStep2");

const loginVideo = document.getElementById("loginVideo");
const loginCanvas = document.getElementById("loginCanvas");
const regVideo = document.getElementById("regVideo");
const regCanvas = document.getElementById("regCanvas");

const geotagVideo = document.getElementById("geotagVideo");
const geotagCanvas = document.getElementById("geotagCanvas");
const geotagCameraBox = document.getElementById("geotagCameraBox");
const cameraRestrictionShield = document.getElementById("cameraRestrictionShield");
const geotagCameraActions = document.getElementById("geotagCameraActions");
const btnOpenGeotagCamera = document.getElementById("btnOpenGeotagCamera");
const btnCloseGeotagCamera = document.getElementById("btnCloseGeotagCamera");
const btnSnapGeotagPhoto = document.getElementById("btnSnapGeotagPhoto");
const simModeSelect = document.getElementById("simModeSelect");

const scanLaser = document.getElementById("scanLaser");
const scanCountdown = document.getElementById("scanCountdown");
const btnTriggerScan = document.getElementById("btnTriggerScan");
const celebrationModal = document.getElementById("celebrationModal");

// State
let isImposterSimulation = false;
let currentGeotagMatchScore = 96.0;
let liveGeoSnapshot = null;
let currentProfileData = null;

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
    const voiceSelect = document.getElementById("voiceSelect");
    if (voiceSelect) {
        voiceSelect.value = biometricAudio.getVoiceGender();
    }
    checkExistingSession();
    // Pre-warm digital fingerprint and GPS coordinates
    digitalFingerprint.collectFullAuditSnapshot().then(snap => {
        liveGeoSnapshot = snap;
    }).catch(() => {});
});

async function checkExistingSession() {
    const token = localStorage.getItem("vault_token");
    if (!token) return;

    try {
        const res = await fetch(getApiUrl("/api/user/profile"), {
            headers: { "Authorization": `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success) {
            renderDashboard(data.user, data.audit_logs, data.geo_captures, data.digital_fingerprint);
        } else {
            localStorage.removeItem("vault_token");
        }
    } catch (e) {
        localStorage.removeItem("vault_token");
    }
}

// --- Tab Switching ---
function switchTab(tab) {
    cameraManager.stopCurrentStream();

    document.getElementById("tabLoginBtn").classList.toggle("active", tab === "login");
    document.getElementById("tabRegisterBtn").classList.toggle("active", tab === "register");

    if (tab === "login") {
        loginView.classList.remove("hidden");
        registerView.classList.add("hidden");
        dashboardView.classList.add("hidden");
        resetLoginFlow();
    } else {
        loginView.classList.add("hidden");
        registerView.classList.remove("hidden");
        dashboardView.classList.add("hidden");
        initRegistrationCamera();
    }
}

// --- Step 1: Credentials Verification ---
async function handleLoginStep1(event) {
    event.preventDefault();
    const loginId = document.getElementById("loginIdInput").value.trim();
    const password = document.getElementById("loginPasswordInput").value;
    const btn = document.getElementById("btnStep1Submit");

    if (!loginId || !password) {
        showToast("error", "Input Required", "Please enter both Login ID and Password.");
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<span>Verifying Credentials...</span>`;

    try {
        const res = await fetch(getApiUrl("/api/auth/step1"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ login_id: loginId, password: password })
        });

        const data = await res.json();

        if (res.ok && data.success) {
            currentLoginId = loginId;
            currentNonce = data.nonce;
            currentUserName = data.full_name;

            // Transition to Step 2
            loginStep1.classList.add("hidden");
            loginStep2.classList.remove("hidden");

            document.getElementById("greetingTargetName").innerText = currentUserName;
            document.getElementById("greetingTargetId").innerText = currentLoginId;

            // Start Camera
            await cameraManager.startCamera(loginVideo);
            biometricAudio.speakCredentialsVerified();
            showToast("info", "Password Verified", "Please align your face inside the target frame for biometric scan.");
        } else {
            biometricAudio.playMismatchTone();
            showToast("error", "Access Denied", data.message || "Invalid credentials.");
        }
    } catch (err) {
        showToast("error", "Connection Error", "Could not reach authentication server.");
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <span>Proceed to Biometric Scan</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        `;
    }
}

function cancelStep2() {
    cameraManager.stopCurrentStream();
    resetLoginFlow();
}

function resetLoginFlow() {
    loginStep1.classList.remove("hidden");
    loginStep2.classList.add("hidden");
    scanLaser.classList.add("hidden");
    scanCountdown.classList.add("hidden");
    currentNonce = null;
    currentLoginId = null;
    btnTriggerScan.disabled = false;
}

// --- Step 2: Biometric Facial Scan ---
async function executeBiometricScan() {
    if (!currentNonce || !currentLoginId) {
        showToast("error", "Session Error", "Session challenge expired. Please start over.");
        resetLoginFlow();
        return;
    }

    btnTriggerScan.disabled = true;
    btnTriggerScan.innerHTML = `<span>Scanning Biometrics...</span>`;

    try {
        // 1. Countdown 3.. 2.. 1..
        scanCountdown.classList.remove("hidden");
        for (let c = 3; c > 0; c--) {
            scanCountdown.innerText = c;
            await new Promise(r => setTimeout(r, 450));
        }
        scanCountdown.classList.add("hidden");

        // 2. Activate Laser Scan & Sound
        scanLaser.classList.remove("hidden");
        try {
            biometricAudio.playScanSweep();
        } catch (e) { }

        // 3. Capture 3-frame burst for liveness & embedding
        const frames = await cameraManager.captureBurst(loginVideo, loginCanvas, 3, 300);

        // 4. Send to server
        const res = await fetch(getApiUrl("/api/auth/step2"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                login_id: currentLoginId,
                nonce: currentNonce,
                frames: frames
            })
        });

        const data = await res.json();

        if (res.ok && data.success && data.matched && (data.confidence >= 80)) {
            // MATCH CONFIRMED! (Strictly Verified >= 80%)
            cameraManager.stopCurrentStream();
            biometricAudio.playCelebrationChime();
            biometricAudio.speakVerified();
            localStorage.setItem("vault_token", data.token);
            sessionUser = data.user;

            // Trigger Celebratory Good Notification Modal
            document.getElementById("modalConfidence").innerText = `${data.confidence}%`;
            document.getElementById("modalUserName").innerText = data.user.full_name;
            celebrationModal.classList.remove("hidden");

        } else {
            // MISMATCH OR INSUFFICIENT CONFIDENCE (< 80% STRICT RULE)
            if (data.new_nonce) {
                currentNonce = data.new_nonce;
            }
            biometricAudio.playMismatchTone();
            if (data.impersonation_caught) {
                biometricAudio.speakSecurityAlert();
                showToast("error", "🚨 SECURITY ALERT: REJECTED", data.message || `Match confidence (${data.confidence || 0}%) is below 80% threshold.`);
            } else {
                biometricAudio.speakMismatch();
                showToast("error", "Access Denied (< 80%)", data.message || `Match confidence (${data.confidence || 0}%) is below required 80% threshold. Please retry.`);
            }
            btnTriggerScan.disabled = false;
            btnTriggerScan.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                <span>Re-try Face Verification</span>
            `;
        }
    } catch (err) {
        btnTriggerScan.disabled = false;
        btnTriggerScan.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>Re-try Face Verification</span>
        `;
        showToast("error", "Scan Failed", "Error processing biometric scan: " + err.message);
    } finally {
        scanLaser.classList.add("hidden");
        scanCountdown.classList.add("hidden");
    }
}

// --- Dismiss Celebration & Unlock Dashboard ---
function dismissCelebrationModal() {
    celebrationModal.classList.add("hidden");
    if (sessionUser) {
        fetchDashboardProfile();
    }
}

// --- Dashboard View ---
async function fetchDashboardProfile() {
    const token = localStorage.getItem("vault_token");
    if (!token) {
        switchTab("login");
        return;
    }

    try {
        const res = await fetch(getApiUrl("/api/user/profile"), {
            headers: { "Authorization": `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success) {
            renderDashboard(data.user, data.audit_logs, data.geo_captures, data.digital_fingerprint);
        } else {
            handleLogout();
        }
    } catch (err) {
        handleLogout();
    }
}

function renderDashboard(user, auditLogs = [], geoCaptures = [], digitalFingerprintData = null) {
    cameraManager.stopCurrentStream();
    closeGeotagCamera();

    authTabs.classList.add("hidden");
    loginView.classList.add("hidden");
    registerView.classList.add("hidden");
    dashboardView.classList.remove("hidden");

    currentProfileData = { user, auditLogs, geoCaptures, digitalFingerprintData };

    document.getElementById("dashName").innerText = user.full_name;
    document.getElementById("dashLoginId").innerText = user.login_id;
    const avatarUrl = getApiUrl(user.avatar);
    document.getElementById("dashAvatar").src = `${avatarUrl}?t=${Date.now()}`;

    // 1. Security Status Banner (Normal vs Flagged)
    const banner = document.getElementById("dashSecurityBanner");
    const bannerIcon = document.getElementById("dashBannerIcon");
    const bannerTitle = document.getElementById("dashBannerTitle");
    const bannerMsg = document.getElementById("dashBannerMessage");
    const bannerBadge = document.getElementById("dashBannerBadge");

    if (user.is_flagged) {
        banner.className = "security-banner banner-flagged";
        bannerIcon.innerText = "⚠️";
        bannerTitle.innerText = "SECURITY ALERT: LOCATION & FINGERPRINT FLAGGED";
        bannerMsg.innerText = user.flag_reason || "Warning: Digital fingerprint or geographical discrepancy recorded. Camera access restricted.";
        bannerBadge.className = "banner-badge badge-flagged";
        bannerBadge.innerText = "STATUS: FLAGGED (< 80%)";
    } else {
        banner.className = "security-banner banner-safe";
        bannerIcon.innerText = "🛡️";
        bannerTitle.innerText = "Biometric & Digital Fingerprint Baseline Active";
        bannerMsg.innerText = `Enrolled baseline sector: ${user.geo_address || "Registered Primary Sector"}. Hardware camera requires >= 80% match.`;
        bannerBadge.className = "banner-badge badge-safe";
        bannerBadge.innerText = "STATUS: SECURE";
    }

    // 2. Telemetry Inspector Cards
    const regLat = user.geo_latitude != null ? user.geo_latitude.toFixed(4) : "22.5726";
    const regLon = user.geo_longitude != null ? user.geo_longitude.toFixed(4) : "88.3639";
    document.getElementById("dashRegCoords").innerText = `${regLat}°, ${regLon}°`;
    document.getElementById("dashRegLocality").innerText = user.geo_address || "Sector: Registered Station";

    const towerSig = digitalFingerprintData?.network?.tower_signature || "TOWER-PROBE-4G";
    const gatewayIp = digitalFingerprintData?.network?.local_gateway || "192.168.1.1";
    document.getElementById("dashTowerSig").innerText = towerSig;
    document.getElementById("dashGatewayIp").innerText = `Gateway: ${gatewayIp}`;

    const devHash = user.device_hash || digitalFingerprintData?.device_hash || "FP-HASH-VERIFIED";
    document.getElementById("dashDeviceHash").innerText = devHash;

    // Probe live coordinates to display deviation
    digitalFingerprint.getGeoCoordinates().then(currGeo => {
        const currLat = currGeo.latitude.toFixed(4);
        const currLon = currGeo.longitude.toFixed(4);
        document.getElementById("dashCurrCoords").innerText = `${currLat}°, ${currLon}°`;

        if (user.geo_latitude != null && user.geo_longitude != null) {
            // Client-side quick deviation distance
            const dLat = (currGeo.latitude - user.geo_latitude) * 111000;
            const dLon = (currGeo.longitude - user.geo_longitude) * 111000;
            const dist = Math.sqrt(dLat * dLat + dLon * dLon);
            const distText = dist > 1000 ? `${(dist / 1000).toFixed(1)} km` : `${Math.round(dist)} m`;
            document.getElementById("dashGeoDistance").innerText = `Deviation: ${distText}`;
        }
    }).catch(() => {});

    // 3. Render Audit Trail
    const tbody = document.getElementById("auditTableBody");
    tbody.innerHTML = "";

    if (!auditLogs || auditLogs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">No recorded security events.</td></tr>`;
    } else {
        auditLogs.forEach(log => {
            const tr = document.createElement("tr");
            let eventBadge = `<span style="color:#10b981; font-weight:600;">✓ ${log.event_type}</span>`;
            if (log.event_type.includes("MISMATCH") || log.event_type.includes("FAILED") || log.event_type.includes("ATTACK") || log.event_type.includes("RESTRICTED") || log.event_type.includes("FLAGGED")) {
                eventBadge = `<span style="color:#ef4444; font-weight:600;">✕ ${log.event_type}</span>`;
            } else if (log.event_type.includes("REGISTERED")) {
                eventBadge = `<span style="color:#00f2fe; font-weight:600;">✚ ${log.event_type}</span>`;
            } else if (log.event_type.includes("GEOTAG")) {
                eventBadge = `<span style="color:#38bdf8; font-weight:600;">📸 ${log.event_type}</span>`;
            }

            const scoreText = log.distance_score ? `${(log.distance_score * 100).toFixed(1)}%` : "N/A";
            const timeFormatted = log.timestamp ? log.timestamp.replace("T", " ").substring(0, 19) : "Just now";

            tr.innerHTML = `
                <td>${eventBadge}</td>
                <td><code>${scoreText}</code></td>
                <td>${log.ip_address || "127.0.0.1"}</td>
                <td>${timeFormatted}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    // 4. Render Geo-Tagged Gallery
    renderGeotagGallery(geoCaptures);
}

function handleLogout() {
    cameraManager.stopCurrentStream();
    closeGeotagCamera();
    localStorage.removeItem("vault_token");
    sessionUser = null;
    currentProfileData = null;
    authTabs.classList.remove("hidden");
    dashboardView.classList.add("hidden");
    showToast("info", "Signed Out", "You have securely signed out of the biometric vault.");
    switchTab("login");
}

// --- Registration & Face Enrollment with Digital Fingerprint Baseline ---

async function initRegistrationCamera() {
    try {
        await cameraManager.startCamera(regVideo);
        updateRegistrationGeoPreview();
    } catch (err) {
        showToast("error", "Camera Error", err.message);
    }
}

async function updateRegistrationGeoPreview() {
    const desc = document.getElementById("regGeoDesc");
    if (!desc) return;
    try {
        const { geo, fp } = await digitalFingerprint.collectFullAuditSnapshot();
        liveGeoSnapshot = { geo, fp };
        const latStr = geo.latitude ? `${geo.latitude.toFixed(4)}° N` : "--";
        const lonStr = geo.longitude ? `${geo.longitude.toFixed(4)}° E` : "--";
        const gw = fp.network?.local_gateway || "192.168.1.1";
        const tower = fp.network?.tower_signature || "TOWER-PRIMARY";
        desc.innerHTML = `📍 GPS: <strong>${latStr}, ${lonStr}</strong> &bull; Gateway Router: <strong>${gw}</strong> (${tower}) &bull; HW: <code>${fp.device_hash.slice(0, 11)}</code>`;
    } catch (e) {
        desc.innerText = "📍 Coordinates & digital router baseline armed for registration.";
    }
}

function captureRegistrationSnapshot() {
    try {
        enrolledSnapshotData = cameraManager.captureFrame(regVideo, regCanvas);
        const preview = document.getElementById("regSnapshotImg");
        const placeholder = document.querySelector(".preview-placeholder");

        preview.src = enrolledSnapshotData;
        preview.classList.remove("hidden");
        if (placeholder) placeholder.classList.add("hidden");

        biometricAudio.playCelebrationChime();
        showToast("success", "Face Captured", "Snapshot captured! Click 'Register & Save Biometrics' to complete.");
    } catch (err) {
        showToast("error", "Capture Error", err.message);
    }
}

async function handleRegistration(event) {
    event.preventDefault();
    const loginId = document.getElementById("regLoginId").value.trim();
    const fullName = document.getElementById("regFullName").value.trim();
    const password = document.getElementById("regPassword").value;
    const btn = document.getElementById("btnRegisterSubmit");

    if (!enrolledSnapshotData) {
        showToast("error", "Biometric Required", "Please click 'Capture Face' to take your facial biometric snapshot.");
        return;
    }

    btn.disabled = true;
    btn.innerHTML = `<span>Binding Digital Fingerprint &amp; Face...</span>`;

    try {
        // Collect fresh geo coordinates and digital fingerprint
        let snapshot = liveGeoSnapshot;
        if (!snapshot || !snapshot.geo) {
            snapshot = await digitalFingerprint.collectFullAuditSnapshot();
        }

        const res = await fetch(getApiUrl("/api/register"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                login_id: loginId,
                full_name: fullName,
                password: password,
                image: enrolledSnapshotData,
                geo_data: snapshot.geo,
                fingerprint_data: snapshot.fp
            })
        });

        const data = await res.json();

        if (res.ok && data.success) {
            biometricAudio.playCelebrationChime();
            biometricAudio.speakRegistrationSuccess();
            showToast("success", "Account Created!", data.message);

            // Reset registration form
            document.getElementById("registerForm").reset();
            enrolledSnapshotData = null;
            document.getElementById("regSnapshotImg").classList.add("hidden");
            const placeholder = document.querySelector(".preview-placeholder");
            if (placeholder) placeholder.classList.remove("hidden");

            // Switch to Login tab with pre-filled ID
            switchTab("login");
            document.getElementById("loginIdInput").value = loginId;
            document.getElementById("loginPasswordInput").focus();
        } else {
            biometricAudio.playMismatchTone();
            showToast("error", "Enrollment Failed", data.message || "Failed to register user.");
        }
    } catch (err) {
        showToast("error", "Server Error", "Could not submit registration: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <span>Register &amp; Save Biometrics</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
        `;
    }
}

// ==========================================================================
// GEO-TAGGED FIELD CAMERA & DIGITAL FINGERPRINT RESTRICTION CONTROLLER
// ==========================================================================

function handleSimulationModeChange(mode) {
    isImposterSimulation = (mode === "imposter");
    if (isImposterSimulation) {
        showToast("info", "🔴 Imposter Mode Active", "Simulating location shift (5 km away) & disconnected router. Match score will drop to ~36% (< 80%) to test restriction.");
    } else {
        showToast("success", "🟢 Normal Mode Active", "Using real GPS sensor & verified device digital fingerprint (>= 80%).");
    }
}

async function handleOpenGeotagCamera() {
    const token = localStorage.getItem("vault_token");
    if (!token) {
        showToast("error", "Session Expired", "Please log in again.");
        switchTab("login");
        return;
    }

    btnOpenGeotagCamera.disabled = true;
    btnOpenGeotagCamera.innerHTML = `<span>Verifying Digital Fingerprint &amp; Location...</span>`;

    try {
        // Collect current live GPS coordinates and digital hardware/network fingerprint
        const { geo, fp } = await digitalFingerprint.collectFullAuditSnapshot();
        liveGeoSnapshot = { geo, fp };

        // Verify with server endpoint
        const res = await fetch(getApiUrl("/api/geo/verify-camera-access"), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
                geo_data: geo,
                fingerprint_data: fp,
                simulate_mismatch: isImposterSimulation
            })
        });

        const data = await res.json();
        currentGeotagMatchScore = data.match_score || 0;

        if (!res.ok || !data.allowed || (data.match_score < 80)) {
            // ===================================================================
            // STRICT RESTRICTION: MATCH SCORE < 80%
            // Restrict camera, show alert shield, and announce via audio!
            // ===================================================================
            cameraManager.stopCurrentStream();

            geotagCameraBox.classList.remove("hidden");
            cameraRestrictionShield.classList.remove("hidden");
            geotagCameraActions.classList.add("hidden");

            btnOpenGeotagCamera.classList.remove("hidden");
            btnCloseGeotagCamera.classList.remove("hidden");

            // Populate shield metrics
            document.getElementById("shieldScoreVal").innerText = `${data.match_score}%`;
            
            const reasonsBox = document.getElementById("shieldReasonsList");
            if (reasonsBox && data.reasons && data.reasons.length > 0) {
                reasonsBox.innerHTML = data.reasons.map(r => `
                    <div class="shield-reason-item"><span>${r}</span></div>
                `).join("");
            }

            // Flag status in UI
            const banner = document.getElementById("dashSecurityBanner");
            if (banner) {
                banner.className = "security-banner banner-flagged";
                document.getElementById("dashBannerIcon").innerText = "⚠️";
                document.getElementById("dashBannerTitle").innerText = "SECURITY ALERT: CAMERA ACCESS RESTRICTED & FLAGGED";
                document.getElementById("dashBannerMessage").innerText = data.message;
                const badge = document.getElementById("dashBannerBadge");
                badge.className = "banner-badge badge-flagged";
                badge.innerText = `RESTRICTED (${data.match_score}% < 80%)`;
            }

            // PLAY AUDIO ALERT (Polite, firm warning as requested)
            biometricAudio.speakGeoRestricted();

            showToast("error", "🔒 CAMERA ACCESS RESTRICTED", `Digital Fingerprint Mismatch (${data.match_score}% < 80%). Flagged in security audit log.`);

            // Refresh audit logs in background to show newly flagged security event
            fetchDashboardProfile();

        } else {
            // ===================================================================
            // ACCESS GRANTED: MATCH SCORE >= 80%
            // Open camera stream, arm watermark overlay, announce via voice!
            // ===================================================================
            cameraRestrictionShield.classList.add("hidden");
            geotagCameraActions.classList.remove("hidden");
            geotagCameraBox.classList.remove("hidden");

            btnOpenGeotagCamera.classList.add("hidden");
            btnCloseGeotagCamera.classList.remove("hidden");

            // Open hardware camera
            await cameraManager.startCamera(geotagVideo);

            // Update Live HUD telemetry tags
            document.getElementById("hudMatchScoreTag").innerText = `MATCH: ${data.match_score}% (VERIFIED)`;
            document.getElementById("wmLiveCoords").innerText = `LAT: ${geo.latitude.toFixed(5)}°, LON: ${geo.longitude.toFixed(5)}° (±${Math.round(geo.accuracy)}m)`;
            document.getElementById("wmLiveUser").innerText = `USER: ${currentProfileData?.user?.full_name || "Verified"}`;
            document.getElementById("wmLiveTime").innerText = `TIME: ${new Date().toISOString().substring(11, 19)} UTC`;
            document.getElementById("wmLiveHash").innerText = `FP: ${fp.device_hash.slice(0, 12)} [VERIFIED]`;

            // Voice announcement
            biometricAudio.speakGeoVerified();

            showToast("success", "Camera Unlocked", `Digital fingerprint and location verified with ${data.match_score}% confidence (>= 80% required).`);
        }

    } catch (err) {
        showToast("error", "Access Verification Error", err.message || "Failed to verify location and fingerprint.");
    } finally {
        btnOpenGeotagCamera.disabled = false;
        btnOpenGeotagCamera.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>Open Camera for Geo-Tag Capture</span>
        `;
    }
}

function closeGeotagCamera() {
    cameraManager.stopCurrentStream();
    if (geotagCameraBox) geotagCameraBox.classList.add("hidden");
    if (cameraRestrictionShield) cameraRestrictionShield.classList.add("hidden");
    if (btnOpenGeotagCamera) btnOpenGeotagCamera.classList.remove("hidden");
    if (btnCloseGeotagCamera) btnCloseGeotagCamera.classList.add("hidden");
}

async function captureGeotagPhoto() {
    const token = localStorage.getItem("vault_token");
    if (!token) return;

    if (currentGeotagMatchScore < 80) {
        showToast("error", "Restricted", "Cannot click picture: Digital fingerprint confidence is below 80%.");
        biometricAudio.speakGeoRestricted();
        return;
    }

    btnSnapGeotagPhoto.disabled = true;
    btnSnapGeotagPhoto.innerHTML = `<span>Watermarking &amp; Geo-Tagging...</span>`;

    try {
        const rawFrame = cameraManager.captureFrame(geotagVideo, geotagCanvas);
        const snapshot = liveGeoSnapshot || await digitalFingerprint.collectFullAuditSnapshot();

        const res = await fetch(getApiUrl("/api/geo/capture-photo"), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
                image: rawFrame,
                geo_data: snapshot.geo,
                fingerprint_data: snapshot.fp,
                match_score: currentGeotagMatchScore
            })
        });

        const data = await res.json();

        if (res.ok && data.success) {
            biometricAudio.playCelebrationChime();
            biometricAudio.speakGeoCaptured();
            showToast("success", "Geo-Tagged Photo Saved!", "Photo watermarked with GPS coordinates & fingerprint stamp.");

            // Refresh profile and gallery
            fetchDashboardProfile();
        } else {
            showToast("error", "Capture Error", data.message || "Could not record geo-tagged photo.");
        }
    } catch (err) {
        showToast("error", "Capture Failed", err.message);
    } finally {
        btnSnapGeotagPhoto.disabled = false;
        btnSnapGeotagPhoto.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19 4h-3.17L14.4 2H9.6L8.17 4H5c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2z"/></svg>
            <span>Click Geo-Tagged Picture</span>
        `;
    }
}

function renderGeotagGallery(captures = []) {
    const grid = document.getElementById("geotagGalleryGrid");
    const countBadge = document.getElementById("galleryCountBadge");
    if (!grid) return;

    if (countBadge) {
        countBadge.innerText = `${captures.length} photo${captures.length === 1 ? '' : 's'}`;
    }

    if (!captures || captures.length === 0) {
        grid.innerHTML = `
            <div class="gallery-empty-state">
                <p>No geo-tagged pictures clicked yet. Verify location &amp; digital fingerprint to capture.</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = captures.map(c => {
        const imgUrl = getApiUrl(c.image_url);
        const lat = c.latitude ? c.latitude.toFixed(5) : "0.0";
        const lon = c.longitude ? c.longitude.toFixed(5) : "0.0";
        const time = c.created_at ? c.created_at.replace("T", " ").substring(0, 19) : "Just now";
        const score = c.match_score ? `${c.match_score}%` : "95%";

        return `
            <div class="gallery-photo-card">
                <div class="photo-thumb-wrap">
                    <img src="${imgUrl}?t=${Date.now()}" alt="Geo-Tagged Photo" loading="lazy">
                </div>
                <div class="photo-meta-box">
                    <span class="photo-coords">GPS: ${lat}°, ${lon}°</span>
                    <div class="photo-badge-row">
                        <span class="photo-score-pill">✓ ${score} MATCH</span>
                        <span class="photo-time">${time}</span>
                    </div>
                    <a href="${imgUrl}" download="${c.image_path || 'geotag.jpg'}" class="btn-download-photo">
                        📥 Download Geo-Tagged Photo
                    </a>
                </div>
            </div>
        `;
    }).join("");
}


// --- Toast Notification System ---
let toastTimeout = null;

function showToast(type, title, message) {
    const toast = document.getElementById("globalToast");
    const icon = document.getElementById("toastIcon");
    const titleEl = document.getElementById("toastTitle");
    const msgEl = document.getElementById("toastMessage");

    if (toastTimeout) clearTimeout(toastTimeout);

    titleEl.innerText = title;
    msgEl.innerText = message;

    if (type === "success") {
        icon.innerText = "✓";
        icon.style.color = "var(--emerald-success)";
        toast.style.borderColor = "var(--emerald-success)";
    } else if (type === "error") {
        icon.innerText = "✕";
        icon.style.color = "var(--danger-red)";
        toast.style.borderColor = "var(--danger-red)";
    } else {
        icon.innerText = "ℹ";
        icon.style.color = "var(--cyan-primary)";
        toast.style.borderColor = "var(--cyan-primary)";
    }

    toast.classList.remove("hidden");
    toastTimeout = setTimeout(() => {
        closeToast();
    }, 4500);
}

function closeToast() {
    const toast = document.getElementById("globalToast");
    toast.classList.add("hidden");
}

// ==========================================================================
// PROGRESSIVE WEB APP (PWA) & MOBILE INTERACTION HANDLERS
// ==========================================================================

// 1. Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('FaceVault PWA ServiceWorker active:', reg.scope))
            .catch(err => console.log('SW registration note:', err));
    });
}

// 2. PWA Install Prompt Listener
let deferredPWAInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPWAInstallPrompt = e;
    
    // Un-hide install buttons on desktop and mobile
    const headerBtn = document.getElementById('btnInstallApp');
    if (headerBtn) headerBtn.classList.remove('hidden');
    
    const modalBtn = document.getElementById('btnModalInstall');
    if (modalBtn) modalBtn.classList.remove('hidden');
});

window.addEventListener('appinstalled', () => {
    deferredPWAInstallPrompt = null;
    document.getElementById('btnInstallApp')?.classList.add('hidden');
    document.getElementById('btnModalInstall')?.classList.add('hidden');
    showToast('success', 'FaceVault Installed', 'App successfully installed to your home screen!');
});

async function triggerPWAInstall() {
    if (deferredPWAInstallPrompt) {
        deferredPWAInstallPrompt.prompt();
        const choice = await deferredPWAInstallPrompt.userChoice;
        if (choice.outcome === 'accepted') {
            showToast('success', 'Installing', 'Adding FaceVault to your home screen...');
        }
        deferredPWAInstallPrompt = null;
        document.getElementById('btnInstallApp')?.classList.add('hidden');
    } else {
        // Fallback instructions for iOS Safari or other browsers
        showToast('info', 'Mobile Install', 'To install: On Android, tap browser menu (⋮) -> "Install app". On iPhone, tap Share (⎋) -> "Add to Home Screen".');
    }
}

// 3. Mobile Connect Modal Handlers
async function openMobileModal() {
    const modal = document.getElementById('mobileModal');
    if (!modal) return;
    modal.classList.remove('hidden');

    try {
        const res = await fetch(getApiUrl('/api/mobile/info'));
        const data = await res.json();
        if (data.success) {
            const displayEl = document.getElementById('mobileUrlDisplay');
            if (displayEl) displayEl.value = data.mobile_url;
            
            const qrImg = document.getElementById('mobileQrImg');
            if (qrImg) qrImg.src = `${getApiUrl('/api/mobile/qr')}?t=${Date.now()}`;
        }
    } catch (e) {
        console.warn('Failed to fetch mobile server info:', e);
    }
}

function closeMobileModal() {
    document.getElementById('mobileModal')?.classList.add('hidden');
}

function copyMobileUrl() {
    const input = document.getElementById('mobileUrlDisplay');
    if (input) {
        input.select();
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(input.value).then(() => {
                showToast('success', 'Copied!', 'Mobile Wi-Fi URL copied to clipboard.');
            }).catch(() => {
                fallbackCopy(input);
            });
        } else {
            fallbackCopy(input);
        }
    }
}

function fallbackCopy(input) {
    input.focus();
    input.select();
    try {
        document.execCommand('copy');
        showToast('success', 'Copied!', 'Mobile Wi-Fi URL copied to clipboard.');
    } catch (e) {
        showToast('info', 'Copy URL', 'Please select and copy the text manually.');
    }
}

