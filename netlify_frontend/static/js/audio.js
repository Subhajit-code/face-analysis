/**
 * Web Audio API Sound Synthesizer & Natural Indian Voice Audio Engine
 * Features:
 *  - Preloading of audio files into memory cache for 0ms playback
 *  - 250ms network watchdog: fall back to native speech synthesis if production connection is slow
 *  - Lifecycle stopAll() mechanism: prevents stale audio from ever playing across page navigation
 */
class BiometricAudioEngine {
    constructor() {
        this.ctx = null;
        this.currentVoice = 'female';
        this.audioCache = {};
        this.currentAudio = null;
        this.watchdogTimer = null;
        this.pendingAlarmTimer = null;
        this.initPreload();
    }

    /**
     * Preloads high-definition audio clips into memory for instant 0ms playback
     */
    initPreload() {
        try {
            const clips = [
                'credentials', 'verified', 'mismatch', 'alert',
                'registered', 'instructions', 'geo_restricted',
                'geo_verified', 'geo_captured'
            ];
            const genders = ['female', 'male'];
            clips.forEach(clip => {
                genders.forEach(gender => {
                    const fn = `${clip}_${gender}.mp3`;
                    const audio = new Audio(`/static/audio_cache/${fn}`);
                    audio.preload = 'auto';
                    this.audioCache[fn] = audio;
                });
            });
        } catch (e) {
            console.warn("Audio preloading skipped:", e);
        }
    }

    /**
     * Immediately stops any currently playing audio, clears network buffers, and cancels speech
     */
    stopAll() {
        if (this.pendingAlarmTimer) {
            clearTimeout(this.pendingAlarmTimer);
            this.pendingAlarmTimer = null;
        }
        if (this.watchdogTimer) {
            clearTimeout(this.watchdogTimer);
            this.watchdogTimer = null;
        }
        if (this.currentAudio) {
            try {
                this.currentAudio.pause();
                this.currentAudio.currentTime = 0;
            } catch (e) {}
            this.currentAudio = null;
        }
        if ('speechSynthesis' in window) {
            try {
                window.speechSynthesis.cancel();
            } catch (e) {}
        }
    }

    initContext() {
        if (!this.ctx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            this.ctx = new AudioContext();
        }
        if (this.ctx.state === 'suspended') {
            this.ctx.resume();
        }
    }

    setVoiceGender(gender) {
        this.currentVoice = (gender === 'male') ? 'male' : 'female';
        try {
            localStorage.setItem('preferred_voice_gender', this.currentVoice);
        } catch (e) {}
    }

    getVoiceGender() {
        try {
            return localStorage.getItem('preferred_voice_gender') || this.currentVoice || 'female';
        } catch (e) {
            return this.currentVoice || 'female';
        }
    }

    /**
     * Futuristic scanning radar hum / laser sweep
     */
    playScanSweep() {
        try {
            this.initContext();
            const now = this.ctx.currentTime;
            
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();
            
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(400, now);
            osc.frequency.exponentialRampToValueAtTime(1200, now + 0.3);
            osc.frequency.exponentialRampToValueAtTime(600, now + 0.6);
            
            gain.gain.setValueAtTime(0.08, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
            
            osc.connect(gain);
            gain.connect(this.ctx.destination);
            
            osc.start(now);
            osc.stop(now + 0.6);
        } catch (e) {}
    }

    /**
     * Celebratory good notification harmonic chime on face match
     */
    playCelebrationChime() {
        try {
            this.initContext();
            const now = this.ctx.currentTime;
            
            // Major triad frequencies for uplifting celebratory chime
            const freqs = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
            
            freqs.forEach((freq, i) => {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                
                osc.type = 'sine';
                osc.frequency.setValueAtTime(freq, now + i * 0.08);
                
                gain.gain.setValueAtTime(0, now + i * 0.08);
                gain.gain.linearRampToValueAtTime(0.18, now + i * 0.08 + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.08 + 0.55);
                
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                
                osc.start(now + i * 0.08);
                osc.stop(now + i * 0.08 + 0.55);
            });
        } catch (e) {}
    }

    /**
     * Low buzz tone on mismatch or error
     */
    playMismatchTone() {
        try {
            this.initContext();
            const now = this.ctx.currentTime;
            
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();
            
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(150, now);
            osc.frequency.linearRampToValueAtTime(110, now + 0.35);
            
            gain.gain.setValueAtTime(0.18, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
            
            osc.connect(gain);
            gain.connect(this.ctx.destination);
            
            osc.start(now);
            osc.stop(now + 0.35);
        } catch (e) {}
    }

    /**
     * Plays ultra-clear natural voice recordings with instant fallback under slow networks.
     */
    playNaturalVoice(clipKey) {
        this.stopAll();

        try {
            const gender = this.getVoiceGender();
            const filename = `${clipKey}_${gender}.mp3`;
            const cachedAudio = this.audioCache[filename];

            // If audio is preloaded in memory and ready, play instantly (0ms latency!)
            if (cachedAudio && cachedAudio.readyState >= 2) {
                this.currentAudio = cachedAudio;
                cachedAudio.currentTime = 0;
                cachedAudio.play().catch(() => this.fallbackSpeech(clipKey));
                return;
            }

            // On slow internet in production, attach a 250ms watchdog.
            // If download takes > 250ms, abort download and speak instantly via native device speech!
            const audio = new Audio(`/static/audio_cache/${filename}`);
            this.currentAudio = audio;
            let started = false;

            this.watchdogTimer = setTimeout(() => {
                if (!started) {
                    try {
                        audio.pause();
                        audio.src = "";
                    } catch (e) {}
                    this.fallbackSpeech(clipKey);
                }
            }, 250);

            audio.onplay = () => {
                started = true;
                if (this.watchdogTimer) {
                    clearTimeout(this.watchdogTimer);
                    this.watchdogTimer = null;
                }
            };

            audio.play().catch(() => {
                if (this.watchdogTimer) {
                    clearTimeout(this.watchdogTimer);
                    this.watchdogTimer = null;
                }
                this.fallbackSpeech(clipKey);
            });
        } catch (e) {
            this.fallbackSpeech(clipKey);
        }
    }

    speakMismatch() {
        this.playNaturalVoice('mismatch');
    }

    speakSecurityAlert() {
        this.playNaturalVoice('alert');
    }

    speakVerified() {
        this.playNaturalVoice('verified');
    }

    speakInstructions() {
        this.playNaturalVoice('instructions');
    }

    speakRegistrationSuccess() {
        this.playNaturalVoice('registered');
    }

    speakCredentialsVerified() {
        this.playNaturalVoice('credentials');
    }

    /**
     * Announces the active head-turn liveness challenge direction. No pre-recorded clip exists
     * for this (direction is randomized per login), so it speaks directly via native TTS.
     */
    speakTurnChallenge(direction) {
        try {
            if (!('speechSynthesis' in window)) return;
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(`Please turn your head to the ${direction}, then back to center.`);
            u.lang = 'en-IN';
            u.rate = 1.0;
            window.speechSynthesis.speak(u);
        } catch (e) {}
    }

    /**
     * Announces camera access restriction when digital fingerprint / geo coordinates fail (< 80%)
     */
    speakGeoRestricted() {
        this.stopAll();
        this.playSecurityLockAlarm();
        this.pendingAlarmTimer = setTimeout(() => {
            this.playNaturalVoice('geo_restricted');
        }, 350);
    }

    /**
     * Announces camera access unlocked when digital fingerprint matches (>= 80%)
     */
    speakGeoVerified() {
        this.stopAll();
        this.playCelebrationChime();
        this.pendingAlarmTimer = setTimeout(() => {
            this.playNaturalVoice('geo_verified');
        }, 300);
    }

    /**
     * Announces successful capture of geo-tagged photograph
     */
    speakGeoCaptured() {
        this.playNaturalVoice('geo_captured');
    }

    /**
     * High-priority warning alarm for restriction/lockout
     */
    playSecurityLockAlarm() {
        try {
            this.initContext();
            const now = this.ctx.currentTime;
            
            [0, 0.18].forEach(offset => {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'square';
                osc.frequency.setValueAtTime(880, now + offset);
                osc.frequency.exponentialRampToValueAtTime(440, now + offset + 0.14);

                gain.gain.setValueAtTime(0.2, now + offset);
                gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.14);

                osc.connect(gain);
                gain.connect(this.ctx.destination);
                osc.start(now + offset);
                osc.stop(now + offset + 0.14);
            });
        } catch (e) {}
    }

    fallbackSpeech(clipKey) {
        try {
            const phrases = {
                'mismatch': 'Face does not match, please retry.',
                'alert': 'Security alert! Impersonation detected. Face does not match registered account.',
                'verified': 'Face match confirmed! Welcome back.',
                'instructions': 'Please look directly at the camera for biometric scan.',
                'registered': 'Registration successful! Your account is now active.',
                'credentials': 'Password verified! Please align your face inside the target frame for biometric scan.',
                'geo_restricted': 'Security alert. Your geographical coordinates and digital fingerprint do not match the registered baseline with the required eighty percent threshold. Camera access has been restricted and this incident has been flagged.',
                'geo_verified': 'Digital fingerprint and location verified. Camera unlocked for geo-tagged capture.',
                'geo_captured': 'Geo-tagged picture captured and verified successfully.'
            };
            const text = phrases[clipKey];
            if (!text) return; // Never speak unrelated error text
            
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(text);
                u.lang = 'en-IN';
                u.rate = 1.0;
                window.speechSynthesis.speak(u);
            }
        } catch (e) {}
    }
}

const biometricAudio = new BiometricAudioEngine();
