/**
 * Biometric Vault - Client-Side Digital Fingerprint & Geolocation Collector Engine
 * Gathers multi-factor device hardware signatures, local network/router topology, and GPS coordinates.
 */
class DigitalFingerprintEngine {
    constructor() {
        this.cachedGeo = null;
        this.cachedFingerprint = null;
    }

    /**
     * Obtains high-accuracy GPS coordinates from the device hardware.
     */
    async getGeoCoordinates(timeoutMs = 8000) {
        if (!navigator.geolocation) {
            return {
                latitude: 22.5726,
                longitude: 88.3639,
                accuracy: 50.0,
                address: "Kolkata Hub (Fallback Sector)",
                status: "UNSUPPORTED"
            };
        }

        return new Promise((resolve) => {
            const timer = setTimeout(() => {
                resolve({
                    latitude: 22.5726,
                    longitude: 88.3639,
                    accuracy: 100.0,
                    address: "Standard GPS Sector (Timeout)",
                    status: "TIMEOUT"
                });
            }, timeoutMs);

            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    clearTimeout(timer);
                    const coords = {
                        latitude: parseFloat(pos.coords.latitude.toFixed(6)),
                        longitude: parseFloat(pos.coords.longitude.toFixed(6)),
                        accuracy: parseFloat((pos.coords.accuracy || 10.0).toFixed(1)),
                        altitude: pos.coords.altitude ? parseFloat(pos.coords.altitude.toFixed(1)) : null,
                        heading: pos.coords.heading || null,
                        speed: pos.coords.speed || null,
                        address: `GPS: ${pos.coords.latitude.toFixed(4)}°, ${pos.coords.longitude.toFixed(4)}° (±${Math.round(pos.coords.accuracy)}m)`,
                        status: "ACCURATE"
                    };
                    this.cachedGeo = coords;
                    resolve(coords);
                },
                (err) => {
                    clearTimeout(timer);
                    console.warn("Geolocation access warning:", err.message);
                    // Default baseline coordinates if user clicks deny in test
                    resolve({
                        latitude: 22.5726,
                        longitude: 88.3639,
                        accuracy: 25.0,
                        address: "Local Gateway Area (Permission Denied/Simulated)",
                        status: "PERMISSION_DENIED"
                    });
                },
                {
                    enableHighAccuracy: true,
                    timeout: timeoutMs,
                    maximumAge: 0
                }
            );
        });
    }

    /**
     * Probes local network router candidate & WebRTC ICE candidate line
     */
    async probeLocalGateway() {
        return new Promise((resolve) => {
            try {
                const RTCPC = window.RTCPeerConnection || window.webkitRTCPeerConnection || window.mozRTCPeerConnection;
                if (!RTCPC) {
                    return resolve({ local_ip: "192.168.1.1", candidate: "default-gateway" });
                }

                const pc = new RTCPC({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
                let resolved = false;

                const finish = (result) => {
                    if (!resolved) {
                        resolved = true;
                        try { pc.close(); } catch (e) {}
                        resolve(result);
                    }
                };

                // Fallback timeout
                setTimeout(() => {
                    finish({ local_ip: "192.168.1.1", candidate: "local-lan-candidate" });
                }, 1200);

                pc.createDataChannel("");
                pc.createOffer().then(offer => pc.setLocalDescription(offer)).catch(() => {});

                pc.onicecandidate = (e) => {
                    if (e && e.candidate && e.candidate.candidate) {
                        const line = e.candidate.candidate;
                        const match = line.match(/([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/);
                        const ip = match ? match[1] : (line.includes(".local") ? "192.168.1.1" : "192.168.0.1");
                        finish({ local_ip: ip, candidate: line.slice(0, 60) });
                    }
                };
            } catch (err) {
                resolve({ local_ip: "192.168.1.1", candidate: "webrtc-restricted" });
            }
        });
    }

    /**
     * Generates 2D Canvas rendering fingerprint hash
     */
    getCanvasFingerprint() {
        try {
            const canvas = document.createElement("canvas");
            canvas.width = 240;
            canvas.height = 60;
            const ctx = canvas.getContext("2d");

            // Cyber gradient & shapes
            const grad = ctx.createLinearGradient(0, 0, 240, 60);
            grad.addColorStop(0, "#00f2fe");
            grad.addColorStop(0.5, "#4facfe");
            grad.addColorStop(1, "#6366f1");
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 240, 60);

            // Text with diverse glyphs
            ctx.fillStyle = "#ffffff";
            ctx.font = "14px 'JetBrains Mono', monospace";
            ctx.fillText("FaceVault-Bio-FP:2026🛡️", 10, 26);
            ctx.font = "11px 'Outfit', sans-serif";
            ctx.fillStyle = "#070913";
            ctx.fillText("AuthSec-ZeroTrust-Verified", 10, 48);

            // Geometric accents
            ctx.beginPath();
            ctx.arc(215, 30, 16, 0, Math.PI * 2);
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            ctx.stroke();

            const dataUri = canvas.toDataURL();
            return this.hashString(dataUri);
        } catch (e) {
            return "canvas-fp-unavailable";
        }
    }

    /**
     * Queries WebGL graphics pipeline & GPU unmasked renderer
     */
    getWebGLFingerprint() {
        try {
            const canvas = document.createElement("canvas");
            const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
            if (!gl) return { renderer: "Software/Generic WebGL", vendor: "Unknown Vendor" };

            const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
            let renderer = "Generic GPU";
            let vendor = "Generic Vendor";

            if (debugInfo) {
                renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || renderer;
                vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) || vendor;
            }

            return {
                renderer: renderer,
                vendor: vendor
            };
        } catch (e) {
            return { renderer: "WebGL Not Supported", vendor: "N/A" };
        }
    }

    /**
     * Probes Web Audio Context oscillator dynamics compressor
     */
    async getAudioFingerprint() {
        return new Promise((resolve) => {
            try {
                const AudioCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
                if (!AudioCtx) return resolve("audio-fp-unsupported");

                const ctx = new AudioCtx(1, 44100, 44100);
                const osc = ctx.createOscillator();
                osc.type = "triangle";
                osc.frequency.setValueAtTime(10000, ctx.currentTime);

                const comp = ctx.createDynamicsCompressor();
                comp.threshold.setValueAtTime(-50, ctx.currentTime);
                comp.knee.setValueAtTime(40, ctx.currentTime);
                comp.ratio.setValueAtTime(12, ctx.currentTime);
                comp.reduction.setValueAtTime(-20, ctx.currentTime);
                comp.attack.setValueAtTime(0, ctx.currentTime);
                comp.release.setValueAtTime(0.25, ctx.currentTime);

                osc.connect(comp);
                comp.connect(ctx.destination);
                osc.start(0);

                ctx.oncomplete = (e) => {
                    const samples = e.renderedBuffer.getChannelData(0);
                    let sum = 0;
                    for (let i = 4500; i < 5000; i++) {
                        sum += Math.abs(samples[i]);
                    }
                    resolve("AUDIO-" + this.hashString(sum.toString()));
                };

                ctx.startRendering();
            } catch (e) {
                resolve("audio-fp-default");
            }
        });
    }

    /**
     * Simple deterministic string hashing (DJB2 + Hex format)
     */
    hashString(str) {
        let hash = 5381;
        for (let i = 0; i < str.length; i++) {
            hash = ((hash << 5) + hash) + str.charCodeAt(i);
            hash = hash & hash;
        }
        return Math.abs(hash).toString(16).toUpperCase().padStart(8, '0');
    }

    /**
     * Collects full digital fingerprint snapshot
     */
    async collectDigitalFingerprint() {
        const localGw = await this.probeLocalGateway();
        const canvasFp = this.getCanvasFingerprint();
        const webgl = this.getWebGLFingerprint();
        const audioFp = await this.getAudioFingerprint();

        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
        const connectionType = conn.effectiveType || conn.type || "wifi";
        const downlink = conn.downlink || 10.0;
        const rtt = conn.rtt || 40;

        const screenSpec = `${window.screen.width}x${window.screen.height}x${window.screen.colorDepth}@${window.devicePixelRatio || 1}`;
        const cpuCores = navigator.hardwareConcurrency || 4;
        const deviceMemory = navigator.deviceMemory || 8;
        const platform = navigator.platform || (navigator.userAgentData ? navigator.userAgentData.platform : "Desktop");
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

        // Deterministic tower signature hash
        const towerSig = "TOWER-" + this.hashString(`${localGw.local_ip}-${connectionType}-${timezone}-${rtt > 50 ? '5G' : '4G'}`);
        const deviceHash = "FP-" + this.hashString(`${canvasFp}-${webgl.renderer}-${screenSpec}-${cpuCores}-${platform}`);

        const result = {
            device_hash: deviceHash,
            network: {
                connection_type: connectionType,
                downlink: downlink,
                rtt: rtt,
                local_gateway: localGw.local_ip,
                candidate: localGw.candidate,
                tower_signature: towerSig
            },
            hardware: {
                canvas_hash: canvasFp,
                webgl_renderer: webgl.renderer,
                webgl_vendor: webgl.vendor,
                audio_hash: audioFp,
                screen: screenSpec,
                cpu_cores: cpuCores,
                device_memory: deviceMemory,
                platform: platform,
                timezone: timezone,
                touch_points: navigator.maxTouchPoints || 0
            }
        };

        this.cachedFingerprint = result;
        return result;
    }

    /**
     * Collects both Geolocation Coordinates and Digital Fingerprint together.
     */
    async collectFullAuditSnapshot() {
        const [geo, fp] = await Promise.all([
            this.getGeoCoordinates(),
            this.collectDigitalFingerprint()
        ]);
        return { geo, fp };
    }
}

const digitalFingerprint = new DigitalFingerprintEngine();
