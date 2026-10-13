/**
 * PartTrackr - UI Controller, Audit Test Harness & Live Diagnostics
 */
document.addEventListener("DOMContentLoaded", () => {
    const player = new MultiTrackAudioEngine();
    let currentScore = null;
    let pollInterval = null;
    let osmd = null;
    let lastRenderedLogsCount = 0;
    let entryCueTimeout = null;

    // ==============================================================
    // DOM ELEMENTS
    // ==============================================================

    // Transport
    const playBtn = document.getElementById("play-btn");
    const pauseBtn = document.getElementById("pause-btn");
    const stopBtn = document.getElementById("stop-btn");
    const seekBar = document.getElementById("seek-bar");
    const timeDisplay = document.getElementById("time-display");
    const masterVolume = document.getElementById("master-volume");
    const masterVolValue = document.getElementById("master-vol-value");

    // Tempo & Metronome
    const tempoMinusBtn = document.getElementById("tempo-minus-btn");
    const tempoPlusBtn = document.getElementById("tempo-plus-btn");
    const tempoResetBtn = document.getElementById("tempo-reset-btn");
    const tempoBpmInput = document.getElementById("tempo-bpm-input");
    const tempoPercentBadge = document.getElementById("tempo-percent-badge");
    const metronomeToggleBtn = document.getElementById("metronome-toggle-btn");
    const metronomeStatusLabel = document.getElementById("metronome-status-label");
    const metronomeVolSlider = document.getElementById("metronome-vol-slider");

    // Measure Navigation & Replay
    const currentMeasureBadge = document.getElementById("current-measure-badge");
    const measureSelect = document.getElementById("measure-select");
    const measureJumpInput = document.getElementById("measure-jump-input");
    const measureJumpBtn = document.getElementById("measure-jump-btn");
    const prevMeasureBtn = document.getElementById("prev-measure-btn");
    const replayMeasureBtn = document.getElementById("replay-measure-btn");
    const nextMeasureBtn = document.getElementById("next-measure-btn");

    // Extended Rest Skipping & Entry Beats
    const skipRestsCheckbox = document.getElementById("skip-rests-checkbox");
    const entryBeatsSelect = document.getElementById("entry-beats-select");
    const entryCueBanner = document.getElementById("entry-cue-banner");
    const entryCueText = document.getElementById("entry-cue-text");

    // Rehearsal Focus Controls
    const targetPartSelect = document.getElementById("target-part-select");
    const modeEmphasizeBtn = document.getElementById("mode-emphasize");
    const modeIsolateBtn = document.getElementById("mode-isolate");
    const emphasisSlider = document.getElementById("emphasis-slider");
    const emphasisValue = document.getElementById("emphasis-value");
    const pianoToggleBtn = document.getElementById("piano-toggle-btn");
    const pianoToggleIndicator = document.getElementById("piano-toggle-indicator");

    // Score Info & Stems
    const currentScoreTitle = document.getElementById("current-score-title");
    const currentScoreSubtitle = document.getElementById("current-score-subtitle");
    const currentScoreStatus = document.getElementById("current-score-status");
    const detectedPartsContainer = document.getElementById("detected-parts-container");
    const stemsContainer = document.getElementById("stems-container");
    const loadingBanner = document.getElementById("loading-banner");
    const loadingText = document.getElementById("loading-text");
    const scoresListContainer = document.getElementById("scores-list");
    const scoreReprocessBtn = document.getElementById("score-reprocess-btn");
    const scoreShowErrorBtn = document.getElementById("score-show-error-btn");
    const scoreDownloadXml = document.getElementById("score-download-xml");
    const scoreDownloadPdf = document.getElementById("score-download-pdf");

    // Error Viewer Elements
    const errorViewerCard = document.getElementById("error-viewer-card");
    const errorStatusBadge = document.getElementById("error-status-badge");
    const errorSummaryText = document.getElementById("error-summary-text");
    const errorDiagnosticTip = document.getElementById("error-diagnostic-tip");
    const errorDiagnosticAdvice = document.getElementById("error-diagnostic-advice");
    const errorTracebackContent = document.getElementById("error-traceback-content");
    const copyTracebackBtn = document.getElementById("copy-traceback-btn");
    const copyTracebackLabel = document.getElementById("copy-traceback-label");
    const errorDismissBtn = document.getElementById("error-dismiss-btn");
    const errorCardReprocessBtn = document.getElementById("error-card-reprocess-btn");

    // Messages Viewer Console Elements
    const messagesCountBadge = document.getElementById("messages-count-badge");
    const autoscrollMessagesToggle = document.getElementById("autoscroll-messages-toggle");
    const copyMessagesBtn = document.getElementById("copy-messages-btn");
    const copyMessagesLabel = document.getElementById("copy-messages-label");
    const clearMessagesBtn = document.getElementById("clear-messages-btn");
    const messagesLogConsole = document.getElementById("messages-log-console");

    // API Viewer Modal Elements
    const openApiViewerBtn = document.getElementById("open-api-viewer-btn");
    const closeApiViewerBtn = document.getElementById("close-api-viewer-btn");
    const apiViewerModal = document.getElementById("api-viewer-modal");
    const apiTabBtnEndpoints = document.getElementById("api-tab-btn-endpoints");
    const apiTabBtnHealth = document.getElementById("api-tab-btn-health");
    const apiTabBtnSwagger = document.getElementById("api-tab-btn-swagger");
    const apiViewEndpoints = document.getElementById("api-view-endpoints");
    const apiViewHealth = document.getElementById("api-view-health");
    const apiViewSwagger = document.getElementById("api-view-swagger");
    const refreshHealthBtn = document.getElementById("refresh-health-btn");
    const healthCardsGrid = document.getElementById("health-cards-grid");
    const rawHealthJson = document.getElementById("raw-health-json");
    const swaggerIframe = document.getElementById("swagger-iframe");

    // Ingestion & Upload
    const fileInput = document.getElementById("file-input");
    const uploadForm = document.getElementById("upload-form");
    const dropZone = document.getElementById("drop-zone");
    const loadSampleBtn = document.getElementById("load-sample-btn");

    // Format seconds into MM:SS
    function formatTime(seconds) {
        if (isNaN(seconds) || seconds < 0) seconds = 0;
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }

    // ==============================================================
    // AUDIO ENGINE EVENT LISTENERS
    // ==============================================================

    player.onTimeUpdate = (current, duration) => {
        timeDisplay.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
        if (duration > 0) {
            seekBar.value = (current / duration) * 100;
        } else {
            seekBar.value = 0;
        }

        // Update individual stem track progress bars
        document.querySelectorAll(".stem-progress-fill").forEach((el) => {
            el.style.width = duration > 0 ? `${(current / duration) * 100}%` : "0%";
        });
    };

    player.onStateChange = (state) => {
        if (state === "playing") {
            playBtn.classList.add("hidden");
            pauseBtn.classList.remove("hidden");
        } else {
            playBtn.classList.remove("hidden");
            pauseBtn.classList.add("hidden");
        }
    };

    player.onTrackLoaded = (track, count, total) => {
        loadingText.textContent = `Buffering audio stem ${count}/${total}: ${track.name}...`;
    };

    player.onAllLoaded = (duration) => {
        loadingBanner.classList.add("hidden");
        timeDisplay.textContent = `00:00 / ${formatTime(duration)}`;
        playBtn.disabled = false;
        renderStemsMixer(currentScore.stems);
    };

    player.onMeasureUpdate = (currentMeasure, totalMeasures, measureObj, currentBeat, totalBeats) => {
        const disp = (measureObj && measureObj.display_number) ? measureObj.display_number : currentMeasure;
        const ts = (measureObj && measureObj.time_signature) ? measureObj.time_signature : "4/4";
        const beatNum = currentBeat || 1;
        const totalB = totalBeats || 4;

        currentMeasureBadge.textContent = `Bar ${disp} [${ts}] • Beat ${beatNum} / ${totalB}`;
        if (measureSelect && measureSelect.value != currentMeasure) {
            measureSelect.value = currentMeasure;
        }

        // Subtle visual flash on downbeat (beat 1)
        if (beatNum === 1) {
            currentMeasureBadge.classList.add("ring-2", "ring-indigo-400");
            setTimeout(() => {
                currentMeasureBadge.classList.remove("ring-2", "ring-indigo-400");
            }, 100);
        }
    };

    player.onEntryCue = (nextMeasure, beats, timeSignature) => {
        if (entryCueBanner && entryCueText) {
            const tsStr = timeSignature ? ` [${timeSignature}]` : "";
            entryCueText.textContent = `Measure ${nextMeasure}${tsStr} entrance in ${beats} beats!`;
            entryCueBanner.classList.remove("hidden");
            if (entryCueTimeout) clearTimeout(entryCueTimeout);
            entryCueTimeout = setTimeout(() => {
                entryCueBanner.classList.add("hidden");
            }, 3500);
        }
    };

    // ==============================================================
    // TRANSPORT CONTROLS
    // ==============================================================

    playBtn.addEventListener("click", () => player.play());
    pauseBtn.addEventListener("click", () => player.pause());
    stopBtn.addEventListener("click", () => player.stop());

    seekBar.addEventListener("input", (e) => {
        const pct = parseFloat(e.target.value) / 100;
        player.seek(pct * player.duration);
    });

    masterVolume.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        player.setMasterVolume(val);
        masterVolValue.textContent = `${Math.round(val * 100)}%`;
    });

    // ==============================================================
    // TEMPO & METRONOME CONTROLS
    // ==============================================================

    function updateTempoUI() {
        tempoBpmInput.value = Math.round(player.currentBpm);
        const pct = Math.round((player.currentBpm / (player.baseBpm || 100)) * 100);
        tempoPercentBadge.textContent = `${pct}% speed`;
    }

    tempoBpmInput.addEventListener("change", (e) => {
        const bpm = parseFloat(e.target.value) || player.baseBpm;
        player.setTempoBpm(bpm);
        updateTempoUI();
    });

    tempoMinusBtn.addEventListener("click", () => {
        player.setTempoBpm(player.currentBpm - 5);
        updateTempoUI();
    });

    tempoPlusBtn.addEventListener("click", () => {
        player.setTempoBpm(player.currentBpm + 5);
        updateTempoUI();
    });

    tempoResetBtn.addEventListener("click", () => {
        player.setTempoBpm(player.baseBpm);
        updateTempoUI();
    });

    metronomeToggleBtn.addEventListener("click", () => {
        player.setMetronomeEnabled(!player.metronomeEnabled);
        if (player.metronomeEnabled) {
            metronomeToggleBtn.className = "px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition flex items-center gap-1.5 shadow";
            metronomeStatusLabel.textContent = "Metronome: ON";
        } else {
            metronomeToggleBtn.className = "px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 font-semibold transition flex items-center gap-1.5 border border-slate-700";
            metronomeStatusLabel.textContent = "Metronome: OFF";
        }
    });

    metronomeVolSlider.addEventListener("input", (e) => {
        player.setMetronomeVolume(e.target.value);
    });

    // ==============================================================
    // MEASURE-BASED NAVIGATION & INSTANT REPLAY
    // ==========================================

    function populateMeasuresDropdown(measures) {
        measureSelect.innerHTML = "";
        if (!measures || measures.length === 0) {
            measureSelect.innerHTML = '<option value="1">Measure 1 [4/4]</option>';
            currentMeasureBadge.textContent = "Bar 1 [4/4] • Beat 1 / 4";
            return;
        }

        measures.forEach((m) => {
            const opt = document.createElement("option");
            opt.value = m.number;
            const disp = m.display_number || m.number;
            const ts = m.time_signature ? ` [${m.time_signature}]` : "";
            const hasEntrance = (m.entrances && m.entrances.length > 0) ? ` • Entr: ${m.entrances.join(",")}` : "";
            opt.textContent = `Bar ${disp}${ts} (${formatTime(m.start_time)})${hasEntrance}`;
            measureSelect.appendChild(opt);
        });

        const first = measures[0];
        const disp = first.display_number || first.number;
        const ts = first.time_signature || "4/4";
        const totalB = first.beats_per_measure || 4;
        currentMeasureBadge.textContent = `Bar ${disp} [${ts}] • Beat 1 / ${totalB}`;
    }

    if (measureJumpBtn && measureJumpInput) {
        const doMeasureJump = () => {
            const val = measureJumpInput.value.trim();
            if (val) {
                player.seekToMeasure(val);
                if (measureSelect) {
                    measureSelect.value = val;
                }
            }
        };
        measureJumpBtn.addEventListener("click", doMeasureJump);
        measureJumpInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                doMeasureJump();
            }
        });
    }

    measureSelect.addEventListener("change", (e) => {
        player.seekToMeasure(e.target.value);
    });

    prevMeasureBtn.addEventListener("click", () => {
        const cur = player.currentMeasureNumber || 1;
        player.seekToMeasure(Math.max(1, cur - 1));
    });

    nextMeasureBtn.addEventListener("click", () => {
        const cur = player.currentMeasureNumber || 1;
        const total = (player.measures && player.measures.length) ? player.measures.length : cur;
        player.seekToMeasure(Math.min(total, cur + 1));
    });

    replayMeasureBtn.addEventListener("click", () => {
        player.replayMeasure(player.currentMeasureNumber || 1);
    });

    // ==============================================================
    // EXTENDED REST SKIPPING & ENTRY BEATS
    // ==========================================

    skipRestsCheckbox.addEventListener("change", (e) => {
        player.skipExtendedRests = e.target.checked;
    });

    entryBeatsSelect.addEventListener("change", (e) => {
        player.entryBeats = parseInt(e.target.value, 10) || 4;
    });

    // ==============================================================
    // REHEARSAL FOCUS CONTROLS
    // ==============================================================

    targetPartSelect.addEventListener("change", (e) => {
        const key = e.target.value;
        player.setTargetPart(key);
        updateActiveTrackHighlight(key);
    });

    modeEmphasizeBtn.addEventListener("click", () => {
        modeEmphasizeBtn.className = "flex-1 py-1.5 px-3 rounded text-xs font-semibold bg-indigo-600 text-white shadow";
        modeIsolateBtn.className = "flex-1 py-1.5 px-3 rounded text-xs font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700";
        player.setRehearsalMode("emphasize");
    });

    modeIsolateBtn.addEventListener("click", () => {
        modeIsolateBtn.className = "flex-1 py-1.5 px-3 rounded text-xs font-semibold bg-indigo-600 text-white shadow";
        modeEmphasizeBtn.className = "flex-1 py-1.5 px-3 rounded text-xs font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700";
        player.setRehearsalMode("isolate");
    });

    emphasisSlider.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        emphasisValue.textContent = `${Math.round(val * 100)}%`;
        player.setEmphasisLevel(val);
    });

    pianoToggleBtn.addEventListener("click", () => {
        player.pianoEnabled = !player.pianoEnabled;
        if (player.pianoEnabled) {
            pianoToggleBtn.className = "px-3 py-1.5 text-xs font-semibold rounded bg-emerald-600 text-white hover:bg-emerald-500 transition";
            pianoToggleIndicator.textContent = "ON";
        } else {
            pianoToggleBtn.className = "px-3 py-1.5 text-xs font-semibold rounded bg-slate-800 text-slate-400 hover:bg-slate-700 transition";
            pianoToggleIndicator.textContent = "OFF";
        }
        player.setPianoEnabled(player.pianoEnabled);
    });

    function updateActiveTrackHighlight(activeKey) {
        document.querySelectorAll(".stem-card").forEach((card) => {
            const key = card.getAttribute("data-part-key");
            if (activeKey && key === activeKey) {
                card.classList.add("ring-2", "ring-indigo-500", "bg-slate-800/80");
            } else {
                card.classList.remove("ring-2", "ring-indigo-500", "bg-slate-800/80");
            }
        });
    }

    // ==============================================================
    // STEMS MIXER RENDERING
    // ==============================================================

    function renderStemsMixer(stems) {
        stemsContainer.innerHTML = "";

        if (!stems || stems.length === 0) {
            stemsContainer.innerHTML = '<div class="text-xs text-slate-500 py-6 text-center">No audio stems rendered yet.</div>';
            return;
        }

        stems.forEach((stem) => {
            const card = document.createElement("div");
            card.className = "stem-card bg-slate-900 border border-slate-800 rounded-lg p-3 transition";
            card.setAttribute("data-part-key", stem.part_key);
            card.setAttribute("data-stem-id", stem.id);

            const isPiano = stem.is_accompaniment;
            const badgeColor = isPiano ? "bg-amber-900/60 text-amber-300 border-amber-700" : "bg-indigo-900/60 text-indigo-300 border-indigo-700";

            card.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center space-x-2">
                        <span class="px-2 py-0.5 text-xs font-mono font-bold rounded border ${badgeColor}">
                            ${stem.part_key}
                        </span>
                        <span class="font-semibold text-slate-100 text-sm">${stem.part_name}</span>
                    </div>
                    <div class="flex items-center space-x-1.5 text-xs text-slate-400">
                        ${stem.pitch_range ? `<span class="bg-slate-800 px-2 py-0.5 rounded">${stem.pitch_range}</span>` : ""}
                        <span class="bg-slate-800 px-2 py-0.5 rounded">${stem.measure_count} bars</span>
                        <span class="bg-slate-800 px-2 py-0.5 rounded">${stem.note_count} notes</span>
                    </div>
                </div>

                <!-- Synchronized Track Waveform Progress -->
                <div class="relative w-full h-2 bg-slate-800 rounded overflow-hidden mb-3">
                    <div class="stem-progress-fill absolute left-0 top-0 h-full bg-indigo-500 w-0 transition-all duration-75"></div>
                </div>

                <!-- Controls: Volume, Pan, Mute, Solo, Downloads -->
                <div class="grid grid-cols-1 md:grid-cols-4 gap-2 items-center text-xs">
                    <div class="flex items-center space-x-2 col-span-2">
                        <span class="text-slate-400 text-[11px] w-6">VOL</span>
                        <input type="range" class="stem-vol-slider w-full accent-indigo-500" min="0" max="1" step="0.05" value="1.0">
                        <span class="stem-vol-val text-slate-400 w-8 text-right font-mono">100%</span>
                    </div>

                    <div class="flex items-center space-x-2">
                        <span class="text-slate-400 text-[11px] w-6">PAN</span>
                        <input type="range" class="stem-pan-slider w-full accent-indigo-500" min="-1" max="1" step="0.1" value="0.0">
                    </div>

                    <div class="flex items-center justify-end space-x-1">
                        <button class="stem-mute-btn px-2 py-1 rounded bg-slate-800 text-slate-300 font-bold hover:bg-slate-700 transition" title="Mute Track">M</button>
                        <button class="stem-solo-btn px-2 py-1 rounded bg-slate-800 text-slate-300 font-bold hover:bg-slate-700 transition" title="Solo Track">S</button>
                        <a href="${stem.audio_url}" download="Stem_${stem.part_key}.wav" class="p-1 rounded bg-slate-800 text-slate-300 hover:text-white hover:bg-slate-700 transition" title="Download Audio WAV">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                        </a>
                        <a href="${stem.midi_url}" download="Stem_${stem.part_key}.mid" class="p-1 rounded bg-slate-800 text-slate-300 hover:text-white hover:bg-slate-700 transition" title="Download MIDI">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"></path></svg>
                        </a>
                    </div>
                </div>
            `;

            const volSlider = card.querySelector(".stem-vol-slider");
            const volVal = card.querySelector(".stem-vol-val");
            const panSlider = card.querySelector(".stem-pan-slider");
            const muteBtn = card.querySelector(".stem-mute-btn");
            const soloBtn = card.querySelector(".stem-solo-btn");

            volSlider.addEventListener("input", (e) => {
                const v = parseFloat(e.target.value);
                volVal.textContent = `${Math.round(v * 100)}%`;
                player.setTrackVolume(stem.id, v);
            });

            panSlider.addEventListener("input", (e) => {
                player.setTrackPan(stem.id, parseFloat(e.target.value));
            });

            muteBtn.addEventListener("click", () => {
                const isMuted = player.toggleTrackMute(stem.id);
                muteBtn.className = isMuted
                    ? "stem-mute-btn px-2 py-1 rounded bg-rose-600 text-white font-bold transition"
                    : "stem-mute-btn px-2 py-1 rounded bg-slate-800 text-slate-300 font-bold hover:bg-slate-700 transition";
            });

            soloBtn.addEventListener("click", () => {
                const isSoloed = player.toggleTrackSolo(stem.id);
                soloBtn.className = isSoloed
                    ? "stem-solo-btn px-2 py-1 rounded bg-amber-500 text-black font-bold transition"
                    : "stem-solo-btn px-2 py-1 rounded bg-slate-800 text-slate-300 font-bold hover:bg-slate-700 transition";
            });

            stemsContainer.appendChild(card);
        });

        if (player.targetPartKey) {
            updateActiveTrackHighlight(player.targetPartKey);
        }
    }

    // ==============================================================
    // MESSAGES CONSOLE RENDERING
    // ==============================================================

    function renderProcessingLogs(logs) {
        if (!logs || !Array.isArray(logs)) logs = [];
        messagesCountBadge.textContent = `${logs.length} ${logs.length === 1 ? 'event' : 'events'}`;

        if (logs.length === 0) {
            messagesLogConsole.innerHTML = `
                <div class="text-slate-500 italic text-[11px] py-4 text-center">
                    No pipeline events logged yet. Upload a score to view real-time processing messages.
                </div>
            `;
            lastRenderedLogsCount = 0;
            return;
        }

        messagesLogConsole.innerHTML = "";
        logs.forEach((log) => {
            const entry = document.createElement("div");
            entry.className = "flex items-start space-x-2 py-0.5 border-b border-slate-900/60 last:border-b-0";

            let stageBadge = "bg-slate-800 text-slate-400 border-slate-700";
            const s = (log.stage || "system").toLowerCase();
            if (s === "omr") stageBadge = "bg-blue-950 text-blue-300 border-blue-800";
            else if (s === "notation") stageBadge = "bg-purple-950 text-purple-300 border-purple-800";
            else if (s === "synthesis") stageBadge = "bg-cyan-950 text-cyan-300 border-cyan-800";
            else if (s === "system") stageBadge = "bg-slate-800 text-slate-300 border-slate-700";

            let msgColor = "text-slate-300";
            const lvl = (log.level || "info").toLowerCase();
            if (lvl === "error") msgColor = "text-rose-400 font-semibold";
            else if (lvl === "success") msgColor = "text-emerald-400 font-semibold";
            else if (lvl === "warning") msgColor = "text-amber-300";

            entry.innerHTML = `
                <span class="text-[10px] text-slate-500 flex-shrink-0 select-none">${log.timestamp ? log.timestamp.split(" ")[1] || log.timestamp : ""}</span>
                <span class="text-[9px] uppercase px-1.5 py-0.2 rounded border font-mono font-bold flex-shrink-0 select-none ${stageBadge}">
                    ${(log.stage || "SYS").toUpperCase()}
                </span>
                <span class="text-xs break-all leading-snug ${msgColor}">
                    ${escapeHtml(log.message)}
                </span>
            `;
            messagesLogConsole.appendChild(entry);
        });

        if (autoscrollMessagesToggle && autoscrollMessagesToggle.checked) {
            messagesLogConsole.scrollTop = messagesLogConsole.scrollHeight;
        }

        lastRenderedLogsCount = logs.length;
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    copyMessagesBtn.addEventListener("click", () => {
        if (!currentScore || !currentScore.processing_logs || currentScore.processing_logs.length === 0) {
            copyMessagesLabel.textContent = "No logs!";
            setTimeout(() => { copyMessagesLabel.textContent = "Copy Logs"; }, 1500);
            return;
        }
        const text = currentScore.processing_logs
            .map((l) => `[${l.timestamp}] [${(l.stage || 'SYS').toUpperCase()}] [${(l.level || 'INFO').toUpperCase()}] ${l.message}`)
            .join("\n");
        navigator.clipboard.writeText(text).then(() => {
            copyMessagesLabel.textContent = "Copied!";
            setTimeout(() => { copyMessagesLabel.textContent = "Copy Logs"; }, 2000);
        });
    });

    clearMessagesBtn.addEventListener("click", () => {
        messagesLogConsole.innerHTML = `
            <div class="text-slate-500 italic text-[11px] py-4 text-center">
                Console cleared.
            </div>
        `;
        messagesCountBadge.textContent = "0 events";
    });

    // ==============================================================
    // ERROR VIEWER LOGIC
    // ==============================================================

    function showErrorViewer(score) {
        errorViewerCard.classList.remove("hidden");
        scoreShowErrorBtn.classList.remove("hidden");

        errorStatusBadge.textContent = (score.status || "FAILED").toUpperCase();
        errorSummaryText.textContent = score.error_message || "An unknown error halted score processing.";

        const msg = (score.error_message || "").toLowerCase();
        const tb = (score.error_traceback || "").toLowerCase();

        if (msg.includes("gtk-3") || tb.includes("gtk-3") || msg.includes("unsatisfiedlinkerror") || tb.includes("unsatisfiedlinkerror")) {
            errorDiagnosticAdvice.innerHTML = `
                <strong>GTK-3 Native Library Link Issue:</strong> Audiveris requires libgtk-3.so for its HiDPI scaling engine. 
                <span class="text-rose-100 font-semibold">Tip:</span> Ensure you have pulled the latest container image via <code>docker compose pull</code>.
            `;
        } else if (msg.includes("audiveris") || msg.includes("omr") || tb.includes("audiveris")) {
            errorDiagnosticAdvice.innerHTML = `
                <strong>Optical Music Recognition (OMR) Failure:</strong> The Audiveris engine was unable to decipher the PDF score staves.
                <span class="text-rose-100 font-semibold">Tip:</span> Verify the PDF has clean black & white notation, or bypass OMR by uploading the score directly in <strong>MusicXML (.musicxml / .mxl / .xml)</strong> or <strong>MIDI (.mid)</strong> format.
            `;
        } else if (msg.includes("notation") || msg.includes("music21") || tb.includes("music21")) {
            errorDiagnosticAdvice.innerHTML = `
                <strong>MusicXML Notation Parsing Error:</strong> music21 encountered unparseable staves or unsupported notation elements.
                <span class="text-rose-100 font-semibold">Tip:</span> Ensure the score contains valid choral voices/parts or re-export the score from MuseScore/Sibelius as standard MusicXML.
            `;
        } else if (msg.includes("synthesis") || msg.includes("fluidsynth") || tb.includes("fluidsynth")) {
            errorDiagnosticAdvice.innerHTML = `
                <strong>SoundFont Audio Synthesis Error:</strong> FluidSynth failed to render audio stems.
                <span class="text-rose-100 font-semibold">Tip:</span> Check that the GM SoundFont file (FluidR3_GM.sf2) is present in the container.
            `;
        } else {
            errorDiagnosticAdvice.textContent = `
                Pipeline encountered an unhandled exception. Inspect the stack trace below for debugging or click "Reprocess Score" to retry.
            `;
        }

        errorTracebackContent.textContent = score.error_traceback || score.error_message || "No full stack trace available.";
        errorViewerCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function hideErrorViewer() {
        errorViewerCard.classList.add("hidden");
        scoreShowErrorBtn.classList.add("hidden");
    }

    errorDismissBtn.addEventListener("click", () => {
        errorViewerCard.classList.add("hidden");
    });

    scoreShowErrorBtn.addEventListener("click", () => {
        if (currentScore && currentScore.status === "failed") {
            errorViewerCard.classList.remove("hidden");
            errorViewerCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    });

    copyTracebackBtn.addEventListener("click", () => {
        const text = errorTracebackContent.textContent;
        navigator.clipboard.writeText(text).then(() => {
            copyTracebackLabel.textContent = "Copied!";
            setTimeout(() => { copyTracebackLabel.textContent = "Copy Traceback"; }, 2000);
        });
    });

    async function reprocessScore(scoreId) {
        if (!scoreId) return;
        loadingBanner.classList.remove("hidden");
        loadingText.textContent = `Triggering reprocess for score...`;
        hideErrorViewer();

        try {
            const res = await fetch(`/api/v1/scores/${scoreId}/reprocess`, { method: "POST" });
            if (!res.ok) throw new Error("Reprocess request failed");
            const score = await res.json();
            currentScore = score;
            displayScoreInfo(score);
            renderProcessingLogs(score.processing_logs);
            pollScoreUntilComplete(scoreId);
        } catch (err) {
            alert(`Reprocess error: ${err.message}`);
            loadingBanner.classList.add("hidden");
        }
    }

    scoreReprocessBtn.addEventListener("click", () => {
        if (currentScore) reprocessScore(currentScore.id);
    });

    errorCardReprocessBtn.addEventListener("click", () => {
        if (currentScore) reprocessScore(currentScore.id);
    });

    // ==============================================================
    // SCORE SELECTION & POLLING
    // ==============================================================

    async function loadScore(scoreId) {
        if (pollInterval) clearInterval(pollInterval);
        loadingBanner.classList.remove("hidden");
        loadingText.textContent = "Fetching score details...";

        try {
            const res = await fetch(`/api/v1/scores/${scoreId}`);
            if (!res.ok) throw new Error("Failed to fetch score");
            const score = await res.json();
            currentScore = score;
            displayScoreInfo(score);
            renderProcessingLogs(score.processing_logs);

            if (score.status === "ready") {
                hideErrorViewer();
                loadingText.textContent = "Loading audio stems into Web Audio context...";
                scoreDownloadXml.href = score.xml_url || "#";
                scoreDownloadPdf.href = score.pdf_url || "#";

                // Setup measures and tempo in player
                if (score.measure_analysis) {
                    player.setMeasureAnalysis(score.measure_analysis);
                    populateMeasuresDropdown(score.measure_analysis.measures);
                    updateTempoUI();
                }

                await player.loadScoreStems(score.stems);
                renderScoreNotation(score.xml_url);
            } else if (score.status === "failed") {
                loadingBanner.classList.add("hidden");
                showErrorViewer(score);
            } else {
                pollScoreUntilComplete(scoreId);
            }
        } catch (err) {
            console.error("Error loading score:", err);
            loadingBanner.classList.add("hidden");
        }
    }

    function pollScoreUntilComplete(scoreId) {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(async () => {
            try {
                const pollRes = await fetch(`/api/v1/scores/${scoreId}`);
                if (!pollRes.ok) return;
                const pollData = await pollRes.json();
                currentScore = pollData;
                displayScoreInfo(pollData);
                renderProcessingLogs(pollData.processing_logs);

                if (pollData.status === "ready") {
                    clearInterval(pollInterval);
                    pollInterval = null;
                    hideErrorViewer();
                    loadScore(scoreId);
                    fetchScoresList();
                } else if (pollData.status === "failed") {
                    clearInterval(pollInterval);
                    pollInterval = null;
                    loadingBanner.classList.add("hidden");
                    showErrorViewer(pollData);
                    fetchScoresList();
                }
            } catch (pollErr) {
                console.error("Polling error:", pollErr);
            }
        }, 1200);
    }

    function displayScoreInfo(score) {
        currentScoreTitle.textContent = score.title || "Untitled Score";
        currentScoreSubtitle.textContent = `${score.composer ? score.composer + " • " : ""}${score.filename}`;

        const statusBadges = {
            queued: "bg-amber-900/60 text-amber-300 border-amber-700",
            processing_omr: "bg-blue-900/60 text-blue-300 border-blue-700",
            parsing: "bg-purple-900/60 text-purple-300 border-purple-700",
            synthesizing: "bg-cyan-900/60 text-cyan-300 border-cyan-700",
            ready: "bg-emerald-900/60 text-emerald-300 border-emerald-700",
            failed: "bg-rose-900/60 text-rose-300 border-rose-700",
        };

        const badgeClass = statusBadges[score.status] || "bg-slate-800 text-slate-300 border-slate-700";
        currentScoreStatus.className = `px-2.5 py-1 text-xs font-semibold rounded-full border ${badgeClass}`;
        currentScoreStatus.textContent = score.status.toUpperCase().replace("_", " ");

        if (score.status === "ready" || score.status === "failed") {
            scoreReprocessBtn.classList.remove("hidden");
        } else {
            scoreReprocessBtn.classList.add("hidden");
        }

        if (score.status === "failed") {
            scoreShowErrorBtn.classList.remove("hidden");
        } else {
            scoreShowErrorBtn.classList.add("hidden");
        }

        // Detected Parts Badges
        detectedPartsContainer.innerHTML = "";
        const parts = score.detected_parts || [];
        if (parts.length === 0) {
            detectedPartsContainer.innerHTML = '<span class="text-xs text-slate-500 italic">None yet</span>';
        } else {
            parts.forEach((part) => {
                const badge = document.createElement("span");
                badge.className = "px-2 py-0.5 text-xs bg-slate-800 text-indigo-300 border border-slate-700 rounded-md font-medium";
                badge.textContent = part;
                detectedPartsContainer.appendChild(badge);
            });
        }
    }

    // ==============================================================
    // NOTATION RENDERING (OSMD)
    // ==============================================================

    async function renderScoreNotation(xmlUrl) {
        if (!xmlUrl || typeof opensheetmusicdisplay === "undefined") return;
        const osmdContainer = document.getElementById("osmd-container");
        if (!osmdContainer) return;
        osmdContainer.innerHTML = "";

        try {
            osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay("osmd-container", {
                autoResize: true,
                drawTitle: false,
                drawSubtitle: false,
                drawComposer: false,
            });
            await osmd.load(xmlUrl);
            osmd.render();
        } catch (e) {
            console.warn("OSMD score rendering preview skipped:", e);
        }
    }

    // ==============================================================
    // SCORES LISTING
    // ==============================================================

    async function fetchScoresList() {
        try {
            const res = await fetch("/api/v1/scores");
            if (!res.ok) return;
            const data = await res.json();
            renderScoresList(data.scores);
        } catch (err) {
            console.error("Failed to fetch scores list:", err);
        }
    }

    function renderScoresList(scores) {
        scoresListContainer.innerHTML = "";
        if (!scores || scores.length === 0) {
            scoresListContainer.innerHTML = '<div class="text-xs text-slate-500 py-3 text-center">No scores uploaded yet. Upload a PDF/MusicXML above.</div>';
            return;
        }

        scores.forEach((s) => {
            const item = document.createElement("div");
            item.className = "p-2.5 bg-slate-900 border border-slate-800 rounded-lg hover:border-slate-700 cursor-pointer transition flex items-center justify-between";
            
            let statusPillClass = "bg-slate-800 text-slate-400";
            if (s.status === "ready") statusPillClass = "bg-emerald-950 text-emerald-400 border border-emerald-800";
            else if (s.status === "failed") statusPillClass = "bg-rose-950 text-rose-300 border border-rose-800";
            else statusPillClass = "bg-amber-950 text-amber-300 border border-amber-800";

            item.innerHTML = `
                <div class="truncate mr-2 flex-1">
                    <div class="text-xs font-semibold text-slate-200 truncate">${s.title}</div>
                    <div class="text-[11px] text-slate-500 truncate">${s.filename} • ${s.stems ? s.stems.length : 0} stems</div>
                </div>
                <div class="flex items-center space-x-1.5 flex-shrink-0">
                    <span class="text-[10px] px-2 py-0.5 rounded font-mono font-bold ${statusPillClass}">
                        ${s.status.toUpperCase()}
                    </span>
                    <button class="delete-score-btn text-slate-500 hover:text-rose-400 p-1 transition" title="Delete Score">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                    </button>
                </div>
            `;

            item.addEventListener("click", (e) => {
                if (e.target.closest(".delete-score-btn")) return;
                loadScore(s.id);
            });

            const delBtn = item.querySelector(".delete-score-btn");
            delBtn.addEventListener("click", async (e) => {
                e.stopPropagation();
                if (confirm(`Delete score "${s.title}" and its audio stems?`)) {
                    await fetch(`/api/v1/scores/${s.id}`, { method: "DELETE" });
                    fetchScoresList();
                    if (currentScore && currentScore.id === s.id) {
                        player.stop();
                        currentScore = null;
                        hideErrorViewer();
                        renderProcessingLogs([]);
                    }
                }
            });

            scoresListContainer.appendChild(item);
        });
    }

    // ==============================================================
    // UPLOAD & SAMPLE HANDLERS
    // ==============================================================

    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("border-indigo-500", "bg-slate-800/50");
    });
    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("border-indigo-500", "bg-slate-800/50");
    });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("border-indigo-500", "bg-slate-800/50");
        if (e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            uploadFile(e.target.files[0]);
        }
    });

    async function uploadFile(file) {
        const formData = new FormData();
        formData.append("file", file);

        loadingBanner.classList.remove("hidden");
        loadingText.textContent = `Uploading score '${file.name}'...`;
        hideErrorViewer();

        try {
            const res = await fetch("/api/v1/scores/upload", {
                method: "POST",
                body: formData,
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Upload failed");
            }
            const data = await res.json();
            await fetchScoresList();
            loadScore(data.id);
        } catch (err) {
            alert(`Upload error: ${err.message}`);
            loadingBanner.classList.add("hidden");
        }
    }

    loadSampleBtn.addEventListener("click", async () => {
        loadingBanner.classList.remove("hidden");
        loadingText.textContent = "Loading sample choral score (Bach SATB & Piano)...";
        hideErrorViewer();
        try {
            const res = await fetch("/api/v1/scores/load-sample", { method: "POST" });
            if (!res.ok) throw new Error("Could not load sample");
            const data = await res.json();
            await fetchScoresList();
            loadScore(data.id);
        } catch (err) {
            alert(`Failed to load sample: ${err.message}`);
            loadingBanner.classList.add("hidden");
        }
    });

    // ==============================================================
    // API VIEWER MODAL CONTROLLER
    // ==============================================================

    openApiViewerBtn.addEventListener("click", () => {
        apiViewerModal.classList.remove("hidden");
        fetchEngineHealth();
    });

    closeApiViewerBtn.addEventListener("click", () => {
        apiViewerModal.classList.add("hidden");
    });

    apiViewerModal.addEventListener("click", (e) => {
        if (e.target === apiViewerModal) {
            apiViewerModal.classList.add("hidden");
        }
    });

    function setApiTab(activeTab) {
        [apiTabBtnEndpoints, apiTabBtnHealth, apiTabBtnSwagger].forEach((btn) => {
            btn.className = "pb-3 text-xs font-medium text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition";
        });
        apiViewEndpoints.classList.add("hidden");
        apiViewHealth.classList.add("hidden");
        apiViewSwagger.classList.add("hidden");

        if (activeTab === "endpoints") {
            apiTabBtnEndpoints.className = "pb-3 text-xs font-bold text-indigo-400 border-b-2 border-indigo-500 transition";
            apiViewEndpoints.classList.remove("hidden");
        } else if (activeTab === "health") {
            apiTabBtnHealth.className = "pb-3 text-xs font-bold text-indigo-400 border-b-2 border-indigo-500 transition";
            apiViewHealth.classList.remove("hidden");
            fetchEngineHealth();
        } else if (activeTab === "swagger") {
            apiTabBtnSwagger.className = "pb-3 text-xs font-bold text-indigo-400 border-b-2 border-indigo-500 transition";
            apiViewSwagger.classList.remove("hidden");
            if (!swaggerIframe.src || swaggerIframe.src === "about:blank") {
                swaggerIframe.src = "/docs";
            }
        }
    }

    apiTabBtnEndpoints.addEventListener("click", () => setApiTab("endpoints"));
    apiTabBtnHealth.addEventListener("click", () => setApiTab("health"));
    apiTabBtnSwagger.addEventListener("click", () => setApiTab("swagger"));
    refreshHealthBtn.addEventListener("click", () => fetchEngineHealth());

    async function fetchEngineHealth() {
        try {
            const res = await fetch("/health");
            if (!res.ok) throw new Error("Health check returned status " + res.status);
            const data = await res.json();
            rawHealthJson.textContent = JSON.stringify(data, null, 2);

            healthCardsGrid.innerHTML = `
                <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-1">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-semibold text-slate-300">FastAPI Microservice</span>
                        <span class="text-[10px] px-2 py-0.5 rounded font-mono font-bold ${data.status === 'healthy' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-300'}">${data.status.toUpperCase()}</span>
                    </div>
                    <p class="text-[11px] text-slate-500">${data.service} v${data.version}</p>
                </div>

                <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-1">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-semibold text-slate-300">Audiveris OMR Engine</span>
                        <span class="text-[10px] px-2 py-0.5 rounded font-mono font-bold ${data.omr_engine_available ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-amber-950 text-amber-300 border border-amber-800'}">
                            ${data.omr_engine_available ? 'ONLINE' : 'FALLBACK MODE'}
                        </span>
                    </div>
                    <p class="text-[11px] text-slate-500">
                        ${data.omr_engine_available ? 'Headless CLI binary active for PDF recognition.' : 'Binary not found in local PATH. MusicXML/MIDI uploads active.'}
                    </p>
                </div>

                <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-1">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-semibold text-slate-300">FluidSynth SoundFont Engine</span>
                        <span class="text-[10px] px-2 py-0.5 rounded font-mono font-bold ${data.fluidsynth_available ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-amber-950 text-amber-300 border border-amber-800'}">
                            ${data.fluidsynth_available ? 'ONLINE' : 'SYNTH FALLBACK'}
                        </span>
                    </div>
                    <p class="text-[11px] text-slate-500">
                        ${data.fluidsynth_available ? 'GM SoundFont active for multi-stem acoustic synthesis.' : 'FluidSynth binary not detected; using tone synthesizer fallback.'}
                    </p>
                </div>

                <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-1">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-semibold text-slate-300">FFmpeg Audio Encoder</span>
                        <span class="text-[10px] px-2 py-0.5 rounded font-mono font-bold ${data.ffmpeg_available ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-slate-800 text-slate-400'}">
                            ${data.ffmpeg_available ? 'ONLINE' : 'NATIVE WAV'}
                        </span>
                    </div>
                    <p class="text-[11px] text-slate-500">
                        ${data.ffmpeg_available ? 'FFmpeg installed for MP3/WAV transcoding.' : 'Using standard WAV encoding.'}
                    </p>
                </div>
            `;
        } catch (err) {
            rawHealthJson.textContent = JSON.stringify({ error: err.message }, null, 2);
            healthCardsGrid.innerHTML = `
                <div class="text-rose-400 text-xs col-span-2 text-center py-4 bg-rose-950/30 rounded-xl border border-rose-900">
                    Failed to reach /health endpoint: ${err.message}
                </div>
            `;
        }
    }

    // Initial load of scores list
    fetchScoresList();
});
