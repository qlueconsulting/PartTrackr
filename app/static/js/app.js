/**
 * PartTrackr - UI Controller & Audit Test Harness
 */
document.addEventListener("DOMContentLoaded", () => {
    const player = new MultiTrackAudioEngine();
    let currentScore = null;
    let pollInterval = null;
    let osmd = null;

    // DOM Elements - Transport
    const playBtn = document.getElementById("play-btn");
    const pauseBtn = document.getElementById("pause-btn");
    const stopBtn = document.getElementById("stop-btn");
    const seekBar = document.getElementById("seek-bar");
    const timeDisplay = document.getElementById("time-display");
    const masterVolume = document.getElementById("master-volume");
    const masterVolValue = document.getElementById("master-vol-value");

    // Rehearsal Controls
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

    // Upload & Sample
    const fileInput = document.getElementById("file-input");
    const uploadForm = document.getElementById("upload-form");
    const dropZone = document.getElementById("drop-zone");
    const loadSampleBtn = document.getElementById("load-sample-btn");
    const scoreDownloadXml = document.getElementById("score-download-xml");
    const scoreDownloadPdf = document.getElementById("score-download-pdf");

    // Format seconds into MM:SS
    function formatTime(seconds) {
        if (isNaN(seconds) || seconds < 0) seconds = 0;
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }

    // ==========================================
    // AUDIO ENGINE EVENT LISTENERS
    // ==========================================

    player.onTimeUpdate = (current, duration) => {
        timeDisplay.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
        if (duration > 0) {
            seekBar.value = (current / duration) * 100;
        } else {
            seekBar.value = 0;
        }

        // Update individual stem track progress indicators
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
        loadingText.textContent = `Buffering audio stems: ${count}/${total} (${track.name})...`;
    };

    player.onAllLoaded = (duration) => {
        loadingBanner.classList.add("hidden");
        timeDisplay.textContent = `00:00 / ${formatTime(duration)}`;
        playBtn.disabled = false;
        renderStemsMixer(currentScore.stems);
    };

    // ==========================================
    // TRANSPORT CONTROLS
    // ==========================================

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

    // ==========================================
    // REHEARSAL CONTROLS
    // ==========================================

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

    // ==========================================
    // STEMS MIXER RENDERING
    // ==========================================

    function renderStemsMixer(stems) {
        stemsContainer.innerHTML = "";
        targetPartSelect.innerHTML = '<option value="">(All Parts Equal)</option>';

        stems.forEach((stem) => {
            // Populate target select
            const opt = document.createElement("option");
            opt.value = stem.part_key;
            opt.textContent = `${stem.part_name} (${stem.part_key})`;
            targetPartSelect.appendChild(opt);

            // Channel Strip Card
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

            // Wire Card Events
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
    }

    // ==========================================
    // SCORE SELECTION & POLLING
    // ==========================================

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

            if (score.status === "ready") {
                loadingText.textContent = "Loading audio stems into Web Audio context...";
                scoreDownloadXml.href = score.xml_url || "#";
                scoreDownloadPdf.href = score.pdf_url || "#";
                await player.loadScoreStems(score.stems);
                renderScoreNotation(score.xml_url);
            } else if (score.status === "failed") {
                loadingBanner.classList.add("hidden");
                alert(`Score processing failed: ${score.error_message}`);
            } else {
                // Poll every 1.5s
                pollInterval = setInterval(async () => {
                    const pollRes = await fetch(`/api/v1/scores/${scoreId}`);
                    const pollData = await pollRes.json();
                    displayScoreInfo(pollData);
                    if (pollData.status === "ready") {
                        clearInterval(pollInterval);
                        loadScore(scoreId);
                    } else if (pollData.status === "failed") {
                        clearInterval(pollInterval);
                        loadingBanner.classList.add("hidden");
                        alert(`Score processing failed: ${pollData.error_message}`);
                    }
                }, 1500);
            }
        } catch (err) {
            console.error("Error loading score:", err);
            loadingBanner.classList.add("hidden");
        }
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

        const badgeClass = statusBadges[score.status] || "bg-slate-800 text-slate-300";
        currentScoreStatus.className = `px-2.5 py-1 text-xs font-semibold rounded-full border ${badgeClass}`;
        currentScoreStatus.textContent = score.status.toUpperCase().replace("_", " ");

        // Detected Parts Badges
        detectedPartsContainer.innerHTML = "";
        (score.detected_parts || []).forEach((part) => {
            const badge = document.createElement("span");
            badge.className = "px-2 py-0.5 text-xs bg-slate-800 text-indigo-300 border border-slate-700 rounded-md font-medium";
            badge.textContent = part;
            detectedPartsContainer.appendChild(badge);
        });
    }

    // ==========================================
    // NOTATION RENDERING (OSMD)
    // ==========================================

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

    // ==========================================
    // SCORES LISTING
    // ==========================================

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
        if (scores.length === 0) {
            scoresListContainer.innerHTML = '<div class="text-xs text-slate-500 py-3 text-center">No scores uploaded yet. Upload a PDF/MusicXML above.</div>';
            return;
        }

        scores.forEach((s) => {
            const item = document.createElement("div");
            item.className = "p-2.5 bg-slate-900 border border-slate-800 rounded-lg hover:border-slate-700 cursor-pointer transition flex items-center justify-between";
            item.innerHTML = `
                <div class="truncate mr-2">
                    <div class="text-xs font-semibold text-slate-200 truncate">${s.title}</div>
                    <div class="text-[11px] text-slate-500 truncate">${s.filename} • ${s.stems ? s.stems.length : 0} stems</div>
                </div>
                <div class="flex items-center space-x-1.5 flex-shrink-0">
                    <span class="text-[10px] px-1.5 py-0.5 rounded ${s.status === 'ready' ? 'bg-emerald-950 text-emerald-400' : 'bg-slate-800 text-slate-400'}">
                        ${s.status}
                    </span>
                    <button class="delete-score-btn text-slate-500 hover:text-rose-400 p-1" title="Delete Score">
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
                if (confirm(`Delete score "${s.title}"?`)) {
                    await fetch(`/api/v1/scores/${s.id}`, { method: "DELETE" });
                    fetchScoresList();
                    if (currentScore && currentScore.id === s.id) {
                        player.stop();
                        currentScore = null;
                    }
                }
            });

            scoresListContainer.appendChild(item);
        });
    }

    // ==========================================
    // UPLOAD & SAMPLE HANDLERS
    // ==========================================

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
        loadingText.textContent = "Loading sample choral score (SATB & Piano)...";
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

    // Initial scores list
    fetchScoresList();
});
