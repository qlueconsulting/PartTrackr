/**
 * PartTrackr - Multi-Track Synchronized Web Audio Player Engine
 * Handles sample-accurate multi-stem synchronized playback,
 * rehearsal part emphasis / isolation, piano toggling, and track routing.
 */
class MultiTrackAudioEngine {
    constructor() {
        this.audioContext = null;
        this.masterGain = null;
        this.tracks = new Map(); // stemId -> TrackObject
        this.isPlaying = false;
        this.startTime = 0;
        this.pauseOffset = 0;
        this.duration = 0;

        // Rehearsal Focus State
        this.targetPartKey = null;       // e.g. "S1", "A1", "Piano"
        this.rehearsalMode = "emphasize"; // "emphasize" or "isolate"
        this.emphasisLevel = 1.5;         // 0.0 to 2.0 (150% default boost)
        this.pianoEnabled = true;         // Quick toggle
        this.masterVolume = 0.9;

        // Event callbacks
        this.onTimeUpdate = null;
        this.onStateChange = null;
        this.onTrackLoaded = null;
        this.onAllLoaded = null;

        this._animationFrame = null;
    }

    initContext() {
        if (!this.audioContext) {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            this.audioContext = new AudioContextClass();
            this.masterGain = this.audioContext.createGain();
            this.masterGain.gain.setValueAtTime(this.masterVolume, this.audioContext.currentTime);
            this.masterGain.connect(this.audioContext.destination);
        }
        if (this.audioContext.state === "suspended") {
            this.audioContext.resume();
        }
    }

    /**
     * Loads stems for a score.
     * @param {Array} stems - Array of stem metadata objects from API.
     */
    async loadScoreStems(stems) {
        this.stop();
        this.tracks.clear();
        this.duration = 0;
        this.pauseOffset = 0;
        this.initContext();

        let loadedCount = 0;
        const total = stems.length;

        for (const stem of stems) {
            const trackObj = {
                id: stem.id,
                key: stem.part_key,
                name: stem.part_name,
                isAccompaniment: stem.is_accompaniment,
                audioUrl: stem.audio_url,
                audioBuffer: null,
                sourceNode: null,
                gainNode: this.audioContext.createGain(),
                panNode: this.audioContext.createStereoPanner ? this.audioContext.createStereoPanner() : null,
                baseVolume: 1.0,
                panValue: 0.0,
                isMuted: false,
                isSoloed: false,
                loaded: false,
            };

            // Connect routing graph: source -> panNode -> gainNode -> masterGain -> destination
            if (trackObj.panNode) {
                trackObj.panNode.connect(trackObj.gainNode);
            }
            trackObj.gainNode.connect(this.masterGain);
            this.tracks.set(stem.id, trackObj);

            // Fetch and decode in background
            try {
                const response = await fetch(stem.audio_url);
                const arrayBuffer = await response.arrayBuffer();
                const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
                trackObj.audioBuffer = audioBuffer;
                trackObj.loaded = true;
                if (audioBuffer.duration > this.duration) {
                    this.duration = audioBuffer.duration;
                }
                loadedCount++;
                if (this.onTrackLoaded) {
                    this.onTrackLoaded(trackObj, loadedCount, total);
                }
            } catch (err) {
                console.error(`Failed to load audio for stem ${stem.part_name}:`, err);
            }
        }

        this.applyMixerSettings();
        if (this.onAllLoaded) {
            this.onAllLoaded(this.duration);
        }
    }

    /**
     * Start synchronized playback across all loaded stems.
     */
    play() {
        if (this.isPlaying || this.tracks.size === 0) return;
        this.initContext();

        const now = this.audioContext.currentTime;
        this.startTime = now - this.pauseOffset;

        // Schedule all tracks to start at precisely now + 0.03s for sample-accurate alignment
        const scheduleTime = now + 0.03;
        const offset = Math.min(this.pauseOffset, this.duration);

        for (const track of this.tracks.values()) {
            if (!track.loaded || !track.audioBuffer) continue;

            // Stop any previous source
            if (track.sourceNode) {
                try { track.sourceNode.stop(); } catch (e) {}
                track.sourceNode.disconnect();
            }

            const src = this.audioContext.createBufferSource();
            src.buffer = track.audioBuffer;

            // Route: Source -> Pan (if available) -> Track Gain
            if (track.panNode) {
                src.connect(track.panNode);
            } else {
                src.connect(track.gainNode);
            }

            // Start synchronized
            src.start(scheduleTime, offset);
            track.sourceNode = src;

            src.onended = () => {
                // If last track ended at end of duration
                if (this.getCurrentTime() >= this.duration - 0.1) {
                    this.stop();
                }
            };
        }

        this.isPlaying = true;
        this._startTimeUpdateLoop();
        if (this.onStateChange) this.onStateChange("playing");
    }

    /**
     * Pause playback and preserve current playback position.
     */
    pause() {
        if (!this.isPlaying) return;
        this.pauseOffset = this.getCurrentTime();
        this._stopSources();
        this.isPlaying = false;
        this._stopTimeUpdateLoop();
        if (this.onStateChange) this.onStateChange("paused");
    }

    /**
     * Stop playback and return transport to 00:00.
     */
    stop() {
        this._stopSources();
        this.pauseOffset = 0;
        this.isPlaying = false;
        this._stopTimeUpdateLoop();
        if (this.onTimeUpdate) this.onTimeUpdate(0, this.duration);
        if (this.onStateChange) this.onStateChange("stopped");
    }

    /**
     * Seek to a specific timestamp in seconds.
     */
    seek(targetSeconds) {
        targetSeconds = Math.max(0, Math.min(targetSeconds, this.duration));
        const wasPlaying = this.isPlaying;
        if (wasPlaying) {
            this._stopSources();
        }
        this.pauseOffset = targetSeconds;
        if (wasPlaying) {
            this.isPlaying = false;
            this.play();
        } else {
            if (this.onTimeUpdate) this.onTimeUpdate(this.pauseOffset, this.duration);
        }
    }

    getCurrentTime() {
        if (this.isPlaying && this.audioContext) {
            return Math.min(this.duration, Math.max(0, this.audioContext.currentTime - this.startTime));
        }
        return this.pauseOffset;
    }

    _stopSources() {
        for (const track of this.tracks.values()) {
            if (track.sourceNode) {
                try {
                    track.sourceNode.stop();
                    track.sourceNode.disconnect();
                } catch (e) {}
                track.sourceNode = null;
            }
        }
    }

    _startTimeUpdateLoop() {
        const loop = () => {
            if (!this.isPlaying) return;
            const current = this.getCurrentTime();
            if (this.onTimeUpdate) {
                this.onTimeUpdate(current, this.duration);
            }
            this._animationFrame = requestAnimationFrame(loop);
        };
        this._animationFrame = requestAnimationFrame(loop);
    }

    _stopTimeUpdateLoop() {
        if (this._animationFrame) {
            cancelAnimationFrame(this._animationFrame);
            this._animationFrame = null;
        }
    }

    // ==========================================
    // REHEARSAL MIXER LOGIC & BALANCING
    // ==========================================

    /**
     * Set target rehearsing part (e.g., "S1", "A1", "T1", "B1", "Piano").
     */
    setTargetPart(partKey) {
        this.targetPartKey = partKey || null;
        this.applyMixerSettings();
    }

    /**
     * Set rehearsal mode: "emphasize" vs "isolate".
     */
    setRehearsalMode(mode) {
        this.rehearsalMode = mode; // "emphasize" or "isolate"
        this.applyMixerSettings();
    }

    /**
     * Set emphasis boost multiplier (0.0 to 2.0).
     */
    setEmphasisLevel(level) {
        this.emphasisLevel = parseFloat(level);
        this.applyMixerSettings();
    }

    /**
     * Quick toggle for Piano Accompaniment.
     */
    setPianoEnabled(enabled) {
        this.pianoEnabled = Boolean(enabled);
        this.applyMixerSettings();
    }

    setMasterVolume(val) {
        this.masterVolume = parseFloat(val);
        if (this.masterGain && this.audioContext) {
            this.masterGain.gain.setTargetAtTime(this.masterVolume, this.audioContext.currentTime, 0.02);
        }
    }

    setTrackVolume(stemId, volume) {
        const track = this.tracks.get(stemId);
        if (track) {
            track.baseVolume = parseFloat(volume);
            this.applyMixerSettings();
        }
    }

    setTrackPan(stemId, panValue) {
        const track = this.tracks.get(stemId);
        if (track && track.panNode && this.audioContext) {
            track.panValue = parseFloat(panValue);
            track.panNode.pan.setTargetAtTime(track.panValue, this.audioContext.currentTime, 0.02);
        }
    }

    toggleTrackMute(stemId) {
        const track = this.tracks.get(stemId);
        if (track) {
            track.isMuted = !track.isMuted;
            this.applyMixerSettings();
            return track.isMuted;
        }
        return false;
    }

    toggleTrackSolo(stemId) {
        const track = this.tracks.get(stemId);
        if (track) {
            track.isSoloed = !track.isSoloed;
            this.applyMixerSettings();
            return track.isSoloed;
        }
        return false;
    }

    /**
     * Recalculates and smoothly updates GainNode for every stem according to:
     * - Rehearsal Target Part & Mode (Emphasize vs Isolate)
     * - Quick Piano Toggle
     * - Individual Track Mute & Solo
     */
    applyMixerSettings() {
        if (!this.audioContext) return;
        const now = this.audioContext.currentTime;

        const anyManualSolo = Array.from(this.tracks.values()).some(t => t.isSoloed);

        for (const track of this.tracks.values()) {
            if (!track.gainNode) continue;

            let computedGain = track.baseVolume;

            // 1. Manual Mute check
            if (track.isMuted) {
                computedGain = 0.0;
            }
            // 2. Manual Solo check
            else if (anyManualSolo) {
                computedGain = track.isSoloed ? track.baseVolume : 0.0;
            }
            // 3. Piano Accompaniment Quick Toggle
            else if (track.isAccompaniment && !this.pianoEnabled) {
                computedGain = 0.0;
            }
            // 4. Target Part Rehearsal Logic
            else if (this.targetPartKey) {
                const isTarget = (track.key === this.targetPartKey);

                if (this.rehearsalMode === "isolate") {
                    if (isTarget) {
                        computedGain = track.baseVolume * 1.0;
                    } else if (track.isAccompaniment) {
                        // Keep piano accompaniment if pianoEnabled is on, else mute
                        computedGain = this.pianoEnabled ? (track.baseVolume * 0.6) : 0.0;
                    } else {
                        // Mute all other vocal parts completely
                        computedGain = 0.0;
                    }
                } else {
                    // "emphasize" Mode
                    if (isTarget) {
                        // Boost target part up to 200%
                        computedGain = track.baseVolume * Math.max(1.0, this.emphasisLevel);
                    } else if (track.isAccompaniment) {
                        // Gentle background accompaniment level
                        computedGain = this.pianoEnabled ? (track.baseVolume * 0.7) : 0.0;
                    } else {
                        // Attenuate other choral vocal parts so target stands out
                        const attenuation = 1.0 / (1.0 + (this.emphasisLevel - 1.0) * 1.8);
                        computedGain = track.baseVolume * Math.min(1.0, Math.max(0.15, attenuation));
                    }
                }
            }

            // Smooth logarithmic volume transition (prevents clipping clicks)
            track.gainNode.gain.setTargetAtTime(computedGain, now, 0.02);
            track.effectiveVolume = computedGain;
        }
    }
}

window.MultiTrackAudioEngine = MultiTrackAudioEngine;
