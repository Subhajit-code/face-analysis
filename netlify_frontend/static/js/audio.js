/**
 * Web Audio API Sound Synthesizer & Natural Indian Voice Audio Engine
 */
class BiometricAudioEngine {
    constructor() {
        this.ctx = null;
        this.currentVoice = 'female';
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
            
            gain.gain.setValueAtTime(0.01, now);
            gain.gain.linearRampToValueAtTime(0.12, now + 0.1);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
            
            const filter = this.ctx.createBiquadFilter();
            filter.type = 'bandpass';
            filter.frequency.setValueAtTime(800, now);
            filter.Q.setValueAtTime(3.0, now);
            
            osc.connect(filter);
            filter.connect(gain);
            gain.connect(this.ctx.destination);
            
            osc.start(now);
            osc.stop(now + 0.6);
        } catch (e) {
            console.warn("Audio unavailable:", e);
        }
    }

    /**
     * Celebratory good notification harmonic chime on face match
     */
    playCelebrationChime() {
        try {
            this.initContext();
            const now = this.ctx.currentTime;
            
            const notes = [523.25, 659.25, 783.99, 1046.50];
            
            notes.forEach((freq, idx) => {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                const noteTime = now + (idx * 0.08);
                
                osc.type = 'sine';
                osc.frequency.setValueAtTime(freq, noteTime);
                
                gain.gain.setValueAtTime(0, noteTime);
                gain.gain.linearRampToValueAtTime(0.2, noteTime + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.001, noteTime + 0.7);
                
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                
                osc.start(noteTime);
                osc.stop(noteTime + 0.7);
            });
        } catch (e) {
            console.warn("Audio unavailable:", e);
        }
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
        } catch (e) {
            console.warn("Audio unavailable:", e);
        }
    }

    /**
     * Plays ultra-clear natural human Indian voice recordings (0ms latency, zero robotic tone)
     */
    playNaturalVoice(clipKey) {
        try {
            const gender = this.getVoiceGender();
            const filename = `${clipKey}_${gender}.mp3`;
            const audioPath = `/static/audio_cache/${filename}`;
            
            const audio = new Audio(audioPath);
            const playPromise = audio.play();
            if (playPromise !== undefined) {
                playPromise.catch(err => {
                    console.warn("Audio element play error, falling back to synthesis:", err);
                    this.fallbackSpeech(clipKey);
                });
            }
        } catch (e) {
            console.warn("Audio play error:", e);
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

    fallbackSpeech(clipKey) {
        try {
            const phrases = {
                'mismatch': 'Face does not match, please retry.',
                'alert': 'Security alert! Impersonation detected. Face does not match registered account.',
                'verified': 'Face match confirmed! Welcome back.',
                'instructions': 'Please look directly at the camera for biometric scan.',
                'registered': 'Registration successful! Your account is now active.',
                'credentials': 'Password verified! Please align your face inside the target frame for biometric scan.'
            };
            const text = phrases[clipKey] || 'Face does not match, please retry.';
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(text);
                u.lang = 'en-IN';
                u.rate = 0.95;
                window.speechSynthesis.speak(u);
            }
        } catch (e) {}
    }
}

const biometricAudio = new BiometricAudioEngine();
