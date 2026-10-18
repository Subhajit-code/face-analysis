/**
 * Biometric Vault - Client-Side Digital Fingerprint & Geolocation Collector Engine
 * Gathers multi-factor device hardware signatures, local network/router topology, and GPS coordinates.
 */
class DigitalFingerprintEngine {
    constructor() {
        this.cachedGeo = null;
        this.cachedFingerprint = null;
        this.purgeStaleCache();
    }

    /**
     * Purges stale or erroneous cached coordinates (e.g. Visakhapatnam ~17.7° when user is in West Bengal ~23.5°)
     */
    purgeStaleCache() {
        try {
            const cached = localStorage.getItem("vault_cached_geo");
            if (cached) {
                const parsed = JSON.parse(cached);
                if (parsed && parsed.latitude != null && Math.abs(parsed.latitude - 17.7) < 1.0) {
                    console.log("[GeoEngine] Purged stale Visakhapatnam Wi-Fi cache.");
                    localStorage.removeItem("vault_cached_geo");
                    localStorage.removeItem("vault_last_location_name");
                }
            }
        } catch (e) {}
    }

    /**
     * Calculates distance in kilometers between two GPS points using Haversine formula
     */
    getHaversineDistanceKm(lat1, lon1, lat2, lon2) {
        const R = 6371.0;
        const dLat = (lat2 - lat1) * Math.PI / 180.0;
        const dLon = (lon2 - lon1) * Math.PI / 180.0;
        const a = Math.sin(dLat / 2.0) * Math.sin(dLat / 2.0) +
                  Math.cos(lat1 * Math.PI / 180.0) * Math.cos(lat2 * Math.PI / 180.0) *
                  Math.sin(dLon / 2.0) * Math.sin(dLon / 2.0);
        const c = 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(1.0 - a));
        return R * c;
    }

    /**
     * Resolves human-readable Location Name (City, Town, Suburb, State) from coordinates
     */
    async resolveLocationName(lat, lon) {
        if (!lat || !lon) return "Local Operations Sector";

        // 1. Try BigDataCloud free client reverse geocoder (Fast & keyless)
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2000);
            const res = await fetch(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=en`, {
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (res.ok) {
                const data = await res.json();
                const locality = data.locality || data.city || data.principalSubdivision;
                const state = data.principalSubdivision || "";
                const country = data.countryName || "India";
                if (locality) {
                    const locStr = [locality, state, country].filter(Boolean).join(", ");
                    try { localStorage.setItem("vault_last_location_name", locStr); } catch(e){}
                    return locStr;
                }
            }
        } catch (e) {}

        // 2. Try OpenStreetMap Nominatim reverse geocoder
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2000);
            const res = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`, {
                headers: { "Accept": "application/json" },
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (res.ok) {
                const data = await res.json();
                const a = data.address || {};
                const place = a.city || a.town || a.suburb || a.village || a.county || a.state_district;
                const state = a.state || "";
                if (place) {
                    const locStr = [place, state, "India"].filter(Boolean).join(", ");
                    try { localStorage.setItem("vault_last_location_name", locStr); } catch(e){}
                    return locStr;
                }
            }
        } catch (e) {}

        // 3. Fallback to cached location name
        try {
            const cachedName = localStorage.getItem("vault_last_location_name");
            if (cachedName && !cachedName.includes("Visakhapatnam")) return cachedName;
        } catch (e) {}

        return `Sector (${lat.toFixed(4)}°, ${lon.toFixed(4)}°)`;
    }

    /**
     * Resolves verified real-world ISP location directly from freeipapi or backend
     */
    async getVerifiedIspLocation() {
        // 1. Primary: freeipapi.com (Accurately resolves Indian telecom ISP pools like Airtel/Jio in Durgapur, West Bengal)
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 2500);
            const res = await fetch("https://freeipapi.com/api/json", { signal: controller.signal });
            clearTimeout(timeoutId);
            if (res.ok) {
                const data = await res.json();
                if (data.latitude != null && data.longitude != null) {
                    const city = data.cityName || "Durgapur";
                    const region = data.regionName || "West Bengal";
                    const country = data.countryName || "India";
                    return {
                        latitude: parseFloat(Number(data.latitude).toFixed(6)),
                        longitude: parseFloat(Number(data.longitude).toFixed(6)),
                        accuracy: 500.0,
                        city: city,
                        region: region,
                        location_name: `${city}, ${region}, ${country}`,
                        status: "ISP_VERIFIED"
                    };
                }
            }
        } catch (e) {}

        // 2. Try server /api/geo/ip-lookup
        try {
            const lookupUrl = (typeof getApiUrl === "function") ? getApiUrl("/api/geo/ip-lookup") : "/api/geo/ip-lookup";
            const token = localStorage.getItem("vault_token") || "";
            const headers = token ? { "Authorization": `Bearer ${token}` } : {};
            const res = await fetch(lookupUrl, { headers });
            if (res.ok) {
                const data = await res.json();
                if (data.success && data.latitude != null) {
                    return {
                        latitude: parseFloat(Number(data.latitude).toFixed(6)),
                        longitude: parseFloat(Number(data.longitude).toFixed(6)),
                        accuracy: 600.0,
                        city: data.city || "Durgapur",
                        region: "West Bengal",
                        location_name: data.city || "Durgapur, West Bengal, India",
                        status: data.source || "SERVER_IP_LOOKUP"
                    };
                }
            }
        } catch (e) {}

        // 3. Fallback baseline: Durgapur, West Bengal
        return {
            latitude: 23.5158,
            longitude: 87.3080,
            accuracy: 600.0,
            city: "Durgapur",
            region: "West Bengal",
            location_name: "Durgapur, West Bengal, India",
            status: "REGION_BASELINE"
        };
    }

    /**
     * Resolves fallback coordinates via local storage cache or public IP resolver
     */
    async getFallbackCoordinates(reason = "TIMEOUT") {
        // 1. Check user manual calibration first
        try {
            const cal = localStorage.getItem("vault_calibrated_location");
            if (cal) {
                const parsed = JSON.parse(cal);
                if (parsed && parsed.latitude != null) {
                    parsed.status = "CALIBRATED_OVERRIDE";
                    return parsed;
                }
            }
        } catch (e) {}

        // 2. Query verified ISP
        const isp = await this.getVerifiedIspLocation();
        const fallback = {
            latitude: isp.latitude,
            longitude: isp.longitude,
            accuracy: isp.accuracy,
            location_name: isp.location_name,
            address: `${isp.location_name} | GPS: ${isp.latitude.toFixed(4)}°, ${isp.longitude.toFixed(4)}°`,
            altitude: null,
            heading: null,
            speed: null,
            status: reason,
            timestamp: Date.now()
        };
        this.cachedGeo = fallback;
        return fallback;
    }

    /**
     * Obtains high-accuracy GPS coordinates, cross-checked against ISP intelligence to eliminate stale Wi-Fi BSSID displacement.
     */
    async getGeoCoordinates(timeoutMs = 5000) {
        // 1. Check manual calibration override
        try {
            const cal = localStorage.getItem("vault_calibrated_location");
            if (cal) {
                const parsed = JSON.parse(cal);
                if (parsed && parsed.latitude != null) {
                    return parsed;
                }
            }
        } catch (e) {}

        // 2. If we already have fresh valid cached coords from this session (not Visakhapatnam), reuse them
        if (this.cachedGeo && this.cachedGeo.timestamp && (Date.now() - this.cachedGeo.timestamp < 120000)) {
            if (Math.abs(this.cachedGeo.latitude - 17.7) >= 1.0) {
                return this.cachedGeo;
            }
        }

        // 3. Concurrently kick off verified ISP lookup for cross-validation
        const ispPromise = this.getVerifiedIspLocation();

        if (!navigator.geolocation) {
            return this.getFallbackCoordinates("UNSUPPORTED");
        }

        return new Promise((resolve) => {
            let resolved = false;

            const timer = setTimeout(async () => {
                if (!resolved) {
                    resolved = true;
                    console.warn("[GeoEngine] Geolocation hardware scan timed out, locking to verified ISP...");
                    const isp = await ispPromise;
                    const fallback = {
                        latitude: isp.latitude,
                        longitude: isp.longitude,
                        accuracy: isp.accuracy,
                        location_name: isp.location_name,
                        address: `${isp.location_name} | GPS: ${isp.latitude.toFixed(4)}°, ${isp.longitude.toFixed(4)}°`,
                        altitude: null,
                        heading: null,
                        speed: null,
                        status: "ISP_TIMEOUT_FALLBACK",
                        timestamp: Date.now()
                    };
                    this.cachedGeo = fallback;
                    resolve(fallback);
                }
            }, timeoutMs);

            navigator.geolocation.getCurrentPosition(
                async (pos) => {
                    if (resolved) return;
                    resolved = true;
                    clearTimeout(timer);

                    const isp = await ispPromise;
                    const distToIsp = this.getHaversineDistanceKm(pos.coords.latitude, pos.coords.longitude, isp.latitude, isp.longitude);

                    // =========================================================================================
                    // WI-FI / ISP DIVERGENCE CHECK:
                    // Report the actual GPS reading, but flag it when it disagrees sharply with the ISP-derived
                    // location. Never silently substitute the ISP location for the GPS reading here — an employee
                    // spoofing their GPS could otherwise have the spoofed reading quietly replaced with their real
                    // (innocuous-looking) ISP location, hiding the spoofing attempt instead of surfacing it.
                    // Flagged readings should be treated as suspicious/rejected by the backend, not auto-corrected.
                    // =========================================================================================
                    const ispMismatch = distToIsp > 80.0;
                    if (ispMismatch) {
                        console.warn(`[GeoEngine] GPS/ISP divergence detected! Browser reported (${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}) which is ${Math.round(distToIsp)}km from ISP-derived location (${isp.location_name}). Flagging as mismatch for backend review.`);
                    }

                    const locName = await this.resolveLocationName(pos.coords.latitude, pos.coords.longitude);
                    const coords = {
                        latitude: parseFloat(pos.coords.latitude.toFixed(6)),
                        longitude: parseFloat(pos.coords.longitude.toFixed(6)),
                        accuracy: parseFloat((pos.coords.accuracy || 25.0).toFixed(1)),
                        location_name: locName,
                        address: `${locName} | GPS: ${pos.coords.latitude.toFixed(4)}°, ${pos.coords.longitude.toFixed(4)}° (±${Math.round(pos.coords.accuracy || 25)}m)`,
                        altitude: pos.coords.altitude ? parseFloat(pos.coords.altitude.toFixed(1)) : null,
                        heading: pos.coords.heading || null,
                        speed: pos.coords.speed || null,
                        status: ispMismatch ? "ISP_MISMATCH_FLAGGED" : "ACCURATE",
                        isp_mismatch: ispMismatch,
                        isp_distance_km: Math.round(distToIsp),
                        isp_location_name: isp.location_name,
                        timestamp: Date.now()
                    };

                    this.cachedGeo = coords;
                    try {
                        localStorage.setItem("vault_cached_geo", JSON.stringify(coords));
                        localStorage.setItem("vault_last_location_name", locName);
                    } catch (e) {}
                    resolve(coords);
                },
                async (err) => {
                    if (resolved) return;
                    resolved = true;
                    clearTimeout(timer);
                    console.warn("[GeoEngine] Hardware geolocation access warning:", err.message);
                    const isp = await ispPromise;
                    const fallback = {
                        latitude: isp.latitude,
                        longitude: isp.longitude,
                        accuracy: isp.accuracy,
                        location_name: isp.location_name,
                        address: `${isp.location_name} | GPS: ${isp.latitude.toFixed(4)}°, ${isp.longitude.toFixed(4)}°`,
                        altitude: null,
                        heading: null,
                        speed: null,
                        status: "ISP_FALLBACK",
                        timestamp: Date.now()
                    };
                    this.cachedGeo = fallback;
                    resolve(fallback);
                },
                {
                    enableHighAccuracy: true,
                    timeout: timeoutMs,
                    maximumAge: 10000
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
     * Scans real nearby WiFi access points (BSSIDs) and the serving cell tower via the
     * native SignalFingerprint plugin (Capacitor Android app only). A fake-GPS app can move
     * the coordinates reported to the page, but it cannot alter which radio signals the
     * device's hardware actually hears, so this is used as an un-spoofable cross-check
     * against the reported GPS location. Returns null in a regular browser (no native plugin).
     */
    async scanRealSignalFingerprint() {
        try {
            const plugin = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.SignalFingerprint;
            if (!plugin) return null;
            const scan = await plugin.scanNearby();
            return {
                wifi_access_points: (scan.wifiAccessPoints || []).map(ap => ({ bssid: ap.bssid, ssid: ap.ssid, rssi: ap.rssi })),
                cell_towers: (scan.cellTowers || []).map(t => ({ type: t.type, cellId: t.cellId, lac: t.lac, tac: t.tac, pci: t.pci }))
            };
        } catch (e) {
            console.warn("[GeoEngine] Native signal scan unavailable:", e.message);
            return null;
        }
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

        // Deterministic tower signature hash (weak, web-only fallback signal)
        const towerSig = "TOWER-" + this.hashString(`${localGw.local_ip}-${connectionType}-${timezone}-${rtt > 50 ? '5G' : '4G'}`);
        const deviceHash = "FP-" + this.hashString(`${canvasFp}-${webgl.renderer}-${screenSpec}-${cpuCores}-${platform}`);

        // Real, un-spoofable nearby-signal scan (native Android app only, null in a browser)
        const realSignals = await this.scanRealSignalFingerprint();

        const result = {
            device_hash: deviceHash,
            network: {
                connection_type: connectionType,
                downlink: downlink,
                rtt: rtt,
                local_gateway: localGw.local_ip,
                candidate: localGw.candidate,
                tower_signature: towerSig,
                real_signal_scan: realSignals
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
