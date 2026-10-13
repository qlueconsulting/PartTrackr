/**
 * PartTrackr - Multi-Track Synchronized Web Audio Player Engine
 * Handles sample-accurate multi-stem synchronized playback,
 * rehearsal part emphasis / isolation, dynamic tempo adjustment,
 * synchronized metronome, measure-based navigation & section replay,
 * and automatic extended rest skipping with entry count-in beats.
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

        // Tempo & Playback Speed
        this.baseBpm = 100.0;
        this.currentBpm = 100.0;
        this.playbackRate = 1.0;

        // Metronome Click Engine
        this.metronomeEnabled = false;
        this.metronomeVolume = 0.8;
        this.beatsPerMeasure = 4;
        this._lastMetronomeBeatKey = null;

        // Measure Structure & Navigation
        this.measures = [];
        this.timeSignatures = [];
        this.partExtendedRests = {};
        this.partEntrances = {};
        this.currentMeasureNumber = 1;
        this.currentMeasureObj = null;
        this.currentBeat = 1;
        this.totalBeatsInMeasure = 4;

        // Extended Rest Skipping & Entry Beats
        this.skipExtendedRests = false;
        this.entryBeats = 4;
        this._lastSkippedRest = null;

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
        this.onMeasureUpdate = null;
        this.onEntryCue = null;

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
     * Ingests measure analysis metadata from the score.
     */
    setMeasureAnalysis(analysis) {
        if (!analysis) return;
        this.measures = analysis.measures || [];
        this.timeSignatures = analysis.time_signatures || [];
        this.baseBpm = analysis.default_bpm || 100.0;
        this.currentBpm = this.baseBpm;
        this.playbackRate = 1.0;
        this.partExtendedRests = analysis.part_extended_rests || {};
        this.partEntrances = analysis.part_entrances || {};
        this._lastSkippedRest = null;
        this._lastMetronomeBeatKey = null;

        if (this.measures.length > 0) {
            this.currentMeasureObj = this.measures[0];
            this.currentMeasureNumber = this.currentMeasureObj.number;
            this.totalBeatsInMeasure = this.currentMeasureObj.beats_per_measure || 4;
            this.currentBeat = 1;
        } else if (analysis.time_signature) {
            const num = parseInt(analysis.time_signature.split("/")[0], 10);
            if (!isNaN(num) && num > 0) this.beatsPerMeasure = num;
        }
    }

    getMeasureAtTime(currentTime) {
        if (!this.measures || this.measures.length === 0) return null;
        for (const m of this.measures) {
            if (currentTime >= m.start_time && currentTime < m.end_time) {
                return m;
            }
        }
        if (currentTime < this.measures[0].start_time) {
            return this.measures[0];
        }
        return this.measures[this.measures.length - 1];
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

            // Connect routing graph: source -> panNode -> gainNode -> masterGain
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
        const currentSec = Math.min(this.pauseOffset, this.duration);
        this.startTime = now - (currentSec / this.playbackRate);

        const scheduleTime = now + 0.03;
        const offset = currentSec;

        for (const track of this.tracks.values()) {
            if (!track.loaded || !track.audioBuffer) continue;

            if (track.sourceNode) {
                try { track.sourceNode.stop(); } catch (e) {}
                track.sourceNode.disconnect();
            }

            const src = this.audioContext.createBufferSource();
            src.buffer = track.audioBuffer;
            src.playbackRate.value = this.playbackRate;

            if (track.panNode) {
                src.connect(track.panNode);
            } else {
                src.connect(track.gainNode);
            }

            src.start(scheduleTime, offset);
            track.sourceNode = src;

            src.onended = () => {
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
        this._lastSkippedRest = null;
        this._lastMetronomeBeatKey = null;
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
        this._lastMetronomeBeatKey = null;

        if (wasPlaying) {
            this.isPlaying = false;
            this.play();
        } else {
            if (this.onTimeUpdate) this.onTimeUpdate(this.pauseOffset, this.duration);
            this._checkMeasureUpdate(this.pauseOffset);
        }
    }

    getCurrentTime() {
        if (this.isPlaying && this.audioContext) {
            const elapsed = (this.audioContext.currentTime - this.startTime) * this.playbackRate;
            return Math.min(this.duration, Math.max(0, elapsed));
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

            // 1. Check Measure Progress
            this._checkMeasureUpdate(current);

            // 2. Metronome Tick Check
            if (this.metronomeEnabled) {
                this._tickMetronome(current);
            }

            // 3. Skip Extended Rests Check
            if (this.skipExtendedRests && this.targetPartKey) {
                this._checkSkipExtendedRests(current);
            }

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
    // TEMPO (BPM) ADJUSTMENT
    // ==========================================

    setTempoBpm(newBpm) {
        newBpm = Math.max(30, Math.min(300, parseFloat(newBpm) || 100));
        this.currentBpm = newBpm;
        this.playbackRate = this.baseBpm > 0 ? this.currentBpm / this.baseBpm : 1.0;

        if (this.audioContext) {
            const now = this.audioContext.currentTime;
            // Update playback rate on all active stems in real-time
            for (const track of this.tracks.values()) {
                if (track.sourceNode && track.sourceNode.playbackRate) {
                    track.sourceNode.playbackRate.setValueAtTime(this.playbackRate, now);
                }
            }
            // Preserve sample-accurate position alignment
            if (this.isPlaying) {
                const cur = this.getCurrentTime();
                this.startTime = now - (cur / this.playbackRate);
            }
        }
    }

    // ==========================================
    // SYNCHRONIZED METRONOME ENGINE (MUSIC-SENSITIVE)
    // ==========================================

    setMetronomeEnabled(enabled) {
        this.metronomeEnabled = !!enabled;
        this._lastMetronomeBeatKey = null;
    }

    setMetronomeVolume(vol) {
        this.metronomeVolume = Math.max(0, Math.min(1, parseFloat(vol) || 0.8));
    }

    _tickMetronome(currentSeconds) {
        if (!this.audioContext || !this.metronomeEnabled) return;
        const m = this.getMeasureAtTime(currentSeconds);
        if (!m) return;

        const elapsedInMeasure = Math.max(0, currentSeconds - m.start_time);
        const beatDur = (m.beat_duration || (60.0 / this.currentBpm)) / this.playbackRate;
        const beatsInBar = m.beats_per_measure || 4;
        const beatIdx = Math.min(beatsInBar - 1, Math.floor(elapsedInMeasure / Math.max(0.01, beatDur)));
        const beatKey = `${m.number}_${beatIdx}`;

        if (beatKey !== this._lastMetronomeBeatKey) {
            this._lastMetronomeBeatKey = beatKey;
            const tonePattern = m.accent_pattern || [1200, 680, 680, 680];
            const toneFreq = tonePattern[beatIdx] !== undefined ? tonePattern[beatIdx] : 680;
            const isDownbeat = (beatIdx === 0);
            const isSecondary = (!isDownbeat && toneFreq >= 900);
            this.playClickTone(toneFreq, isDownbeat, isSecondary, beatDur);
        }
    }

    playClickTone(frequency = 1200, isDownbeat = false, isSecondary = false, beatDurationSec = 0.5) {
        if (!this.audioContext || this.metronomeVolume <= 0.01) return;
        try {
            const now = this.audioContext.currentTime;
            const osc = this.audioContext.createOscillator();
            const gain = this.audioContext.createGain();

            osc.type = "sine";
            osc.frequency.setValueAtTime(frequency, now);

            // Dynamic gain weight & tone decay based on meter beat accent and note length
            let gainMultiplier = 0.55;
            let decayTime = 0.028;
            if (isDownbeat) {
                gainMultiplier = 1.0;
                decayTime = 0.045;
            } else if (isSecondary) {
                gainMultiplier = 0.78;
                decayTime = 0.035;
            }

            // Adjust tone duration for fast meters (e.g. eighth notes)
            if (beatDurationSec < 0.35) {
                decayTime = Math.max(0.02, decayTime * 0.75);
            }

            const peakGain = gainMultiplier * this.metronomeVolume;
            gain.gain.setValueAtTime(peakGain, now);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + decayTime);

            osc.connect(gain);
            gain.connect(this.masterGain);

            osc.start(now);
            osc.stop(now + decayTime + 0.01);
        } catch (e) {}
    }

    // ==========================================
    // MEASURE-BASED NAVIGATION & INSTANT REPLAY
    // ==========================================

    _checkMeasureUpdate(currentTime) {
        if (!this.measures || this.measures.length === 0) return;
        const m = this.getMeasureAtTime(currentTime);
        if (!m) return;

        const elapsedInMeasure = Math.max(0, currentTime - m.start_time);
        const beatDur = (m.beat_duration || (60.0 / this.currentBpm)) / this.playbackRate;
        const beatsInBar = m.beats_per_measure || 4;
        const currentBeat = Math.min(beatsInBar, Math.floor(elapsedInMeasure / Math.max(0.01, beatDur)) + 1);

        const measureChanged = (m.number !== this.currentMeasureNumber);
        const beatChanged = (currentBeat !== this.currentBeat);

        this.currentMeasureNumber = m.number;
        this.currentMeasureObj = m;
        this.currentBeat = currentBeat;
        this.totalBeatsInMeasure = beatsInBar;

        if (this.onMeasureUpdate && (measureChanged || beatChanged)) {
            this.onMeasureUpdate(m.number, this.measures.length, m, currentBeat, beatsInBar);
        }
    }

    seekToMeasure(measureNumber) {
        if (!this.measures || this.measures.length === 0) return;
        const target = this.measures.find(
            (m) => m.number == measureNumber || m.display_number == measureNumber || String(m.number) === String(measureNumber)
        );
        if (target) {
            this.seek(target.start_time);
        }
    }

    replayMeasure(measureNumber) {
        if (!this.measures || this.measures.length === 0) return;
        const target = this.measures.find(
            (m) => m.number == measureNumber || m.display_number == measureNumber || String(m.number) === String(measureNumber)
        );
        if (target) {
            this.seek(target.start_time);
            if (!this.isPlaying) this.play();
        }
    }

    // ==========================================
    // EXTENDED REST SKIPPING & ENTRY BEATS
    // ==========================================

    _checkSkipExtendedRests(currentTime) {
        if (!this.targetPartKey || !this.partExtendedRests) return;
        const rests = this.partExtendedRests[this.targetPartKey] || [];
        if (rests.length === 0) return;

        for (const r of rests) {
            // Find target entry measure to determine metric beat length for the count-in
            const entryMeasure = this.measures.find((m) => m.number === r.next_entry_measure) || this.measures[0];
            const beatDur = (entryMeasure.beat_duration || (60.0 / this.currentBpm)) / this.playbackRate;
            const countInSec = this.entryBeats * beatDur;

            const restStart = r.start_time;
            const jumpTarget = Math.max(0, r.next_entry_time - countInSec);

            if (currentTime >= restStart + 0.25 && currentTime < jumpTarget - 0.4) {
                if (this._lastSkippedRest !== r.start_measure) {
                    this._lastSkippedRest = r.start_measure;
                    // Skip directly to entry count-in position
                    this.seek(jumpTarget);

                    if (this.onEntryCue) {
                        this.onEntryCue(r.next_entry_measure, this.entryBeats, entryMeasure.time_signature);
                    }
                    break;
                }
            }
        }
    }

    // ==========================================
    // REHEARSAL MIXER LOGIC & BALANCING
    // ==========================================

    setTargetPart(partKey) {
        this.targetPartKey = partKey || null;
        this._lastSkippedRest = null;
        this.applyMixerSettings();
    }

    setRehearsalMode(mode) {
        this.rehearsalMode = mode === "isolate" ? "isolate" : "emphasize";
        this.applyMixerSettings();
    }

    setEmphasisLevel(level) {
        this.emphasisLevel = Math.max(0, Math.min(2.0, parseFloat(level) || 1.5));
        this.applyMixerSettings();
    }

    setPianoEnabled(enabled) {
        this.pianoEnabled = !!enabled;
        this.applyMixerSettings();
    }

    setMasterVolume(val) {
        this.masterVolume = Math.max(0, Math.min(1.0, parseFloat(val) || 0.9));
        if (this.masterGain && this.audioContext) {
            this.masterGain.gain.setValueAtTime(this.masterVolume, this.audioContext.currentTime);
        }
    }

    setTrackVolume(stemId, volume) {
        const track = this.tracks.get(stemId);
        if (track) {
            track.baseVolume = Math.max(0, Math.min(1.0, volume));
            this.applyMixerSettings();
        }
    }

    setTrackPan(stemId, pan) {
        const track = this.tracks.get(stemId);
        if (track && track.panNode && this.audioContext) {
            track.panValue = Math.max(-1.0, Math.min(1.0, pan));
            track.panNode.pan.setValueAtTime(track.panValue, this.audioContext.currentTime);
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

    applyMixerSettings() {
        if (!this.audioContext) return;
        const now = this.audioContext.currentTime;

        const anySolo = Array.from(this.tracks.values()).some((t) => t.isSoloed);

        for (const track of this.tracks.values()) {
            let effectiveGain = track.baseVolume;

            if (track.isAccompaniment && !this.pianoEnabled) {
                effectiveGain = 0.0;
            } else if (track.isMuted) {
                effectiveGain = 0.0;
            } else if (anySolo) {
                effectiveGain = track.isSoloed ? track.baseVolume : 0.0;
            } else if (this.targetPartKey) {
                const isTarget = track.key === this.targetPartKey;

                if (this.rehearsalMode === "isolate") {
                    if (isTarget) {
                        effectiveGain = track.baseVolume;
                    } else if (track.isAccompaniment) {
                        effectiveGain = this.pianoEnabled ? track.baseVolume * 0.4 : 0.0;
                    } else {
                        effectiveGain = 0.0;
                    }
                } else if (this.rehearsalMode === "emphasize") {
                    if (isTarget) {
                        effectiveGain = track.baseVolume * this.emphasisLevel;
                    } else {
                        effectiveGain = track.baseVolume * Math.max(0.05, 1.0 - (this.emphasisLevel - 1.0) * 0.7);
                    }
                }
            }

            effectiveGain = Math.max(0.0, Math.min(2.5, effectiveGain));
            track.gainNode.gain.cancelScheduledValues(now);
            track.gainNode.gain.linearRampToValueAtTime(effectiveGain, now + 0.03);
        }
    }
}
