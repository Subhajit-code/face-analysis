/**
 * Camera Stream Manager
 * Handles hardware camera access, video canvas projection, and snapshot sampling.
 */
class CameraManager {
    constructor() {
        this.activeStream = null;
        this.activeVideoEl = null;
    }

    /**
     * Starts webcam stream on the specified <video> element.
     */
    async startCamera(videoElement) {
        this.stopCurrentStream();
        this.activeVideoEl = videoElement;

        try {
            const constraints = {
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    facingMode: "user"
                },
                audio: false
            };

            this.activeStream = await navigator.mediaDevices.getUserMedia(constraints);
            videoElement.srcObject = this.activeStream;
            await videoElement.play();
            return true;
        } catch (err) {
            console.error("Camera access error:", err);
            throw new Error("Unable to access webcam. Please ensure your camera is connected and permissions are granted.");
        }
    }

    /**
     * Stops the active video tracks to release the webcam hardware.
     */
    stopCurrentStream() {
        if (this.activeStream) {
            this.activeStream.getTracks().forEach(track => track.stop());
            this.activeStream = null;
        }
        if (this.activeVideoEl) {
            this.activeVideoEl.srcObject = null;
            this.activeVideoEl = null;
        }
    }

    /**
     * Grabs a single frame from the video stream as a Base64 JPEG.
     */
    captureFrame(videoElement, canvasElement) {
        if (!videoElement || !videoElement.videoWidth) {
            throw new Error("Video feed is not ready");
        }

        const width = videoElement.videoWidth;
        const height = videoElement.videoHeight;

        canvasElement.width = width;
        canvasElement.height = height;

        const ctx = canvasElement.getContext("2d");
        // Mirror the canvas draw to match user's mirror view
        ctx.translate(width, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(videoElement, 0, 0, width, height);

        // Reset transform
        ctx.setTransform(1, 0, 0, 1, 0, 0);

        return canvasElement.toDataURL("image/jpeg", 0.88);
    }

    /**
     * Captures a sequential burst of frames over a brief interval for liveness verification.
     */
    async captureBurst(videoElement, canvasElement, count = 3, intervalMs = 350) {
        const frames = [];
        for (let i = 0; i < count; i++) {
            const frame = this.captureFrame(videoElement, canvasElement);
            frames.push(frame);
            if (i < count - 1) {
                await new Promise(r => setTimeout(r, intervalMs));
            }
        }
        return frames;
    }
}

const cameraManager = new CameraManager();
