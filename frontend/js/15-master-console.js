(() => {
  'use strict';
  const root = window.LGMDM = window.LGMDM || {};
  root.masterConsole = root.masterConsole || {};
  const $ = (id) => document.getElementById(id);
  const state = {
    raf: 0, start: performance.now(), playing: false, audio: null,
    ab: 'master', applying: false,
    stageBypass: { input: false, comp: false, stereo: false, limiter: false },
    metrics: null, spectrum: [], waveHistory: [],
  };

  const refs = {
    input: ['s-ingain', 'consoleInputFader'],
    compThreshold: ['s-thresh', 'consoleCompThreshold'],
    compRatio: ['s-ratio', 'consoleCompRatio'],
    stereo: ['s-width', 'consoleStereoFader'],
    limiter: ['s-ceiling', 'consoleLimiterFader'],
  };

  function mirror(srcId, dstId) {
    const src = LGMDM.dom.byId(srcId), dst = LGMDM.dom.byId(dstId);
    if (!src || !dst) return;
    dst.value = src.value;
    const event = dst.tagName === 'SELECT' || dst.type === 'checkbox' ? 'change' : 'input';
    dst.addEventListener(event, () => {
      src.value = dst.value;
      src.dispatchEvent(new Event(event, { bubbles: true }));
      updateReadouts();
      updateStageCards();
    });
    src.addEventListener('input', () => { dst.value = src.value; updateReadouts(); });
    src.addEventListener('change', () => { dst.value = src.value; updateReadouts(); updateStageCards(); });
  }

    function formatDb(v) { return `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)} dB`; }
  function ceilingDb(v) { return 20 * Math.log10(Math.max(0.01, Number(v))); }

      function toggleStage(stage) {
    state.stageBypass[stage] = !state.stageBypass[stage];
    const related = {
      comp: ['s-thresh', 's-ratio'],
      stereo: ['s-width'],
      limiter: ['s-ceiling'],
    }[stage] || [];
    related.forEach((id) => {
      const el = LGMDM.dom.byId(id);
      if (!el) return;
      if (state.stageBypass[stage]) {
        if (el.dataset.consoleSaved == null) el.dataset.consoleSaved = el.value;
        if (stage === 'comp') el.value = id === 's-ratio' ? '1' : '0';
        if (stage === 'stereo') el.value = '1';
        if (stage === 'limiter') el.value = '0.999';
      } else if (el.dataset.consoleSaved != null) {
        el.value = el.dataset.consoleSaved;
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
    updateReadouts(); updateStageCards(); scheduleConsolePreview();
  }

  function updateReadouts() {
    const input = Number(LGMDM.dom.byId('s-ingain')?.value ?? 0);
    const ct = Number(LGMDM.dom.byId('s-thresh')?.value ?? -18);
    const cr = Number(LGMDM.dom.byId('s-ratio')?.value ?? 4);
    const sw = Number(LGMDM.dom.byId('s-width')?.value ?? 1);
    const ceil = Number(LGMDM.dom.byId('s-ceiling')?.value ?? .891);
    if (LGMDM.dom.byId('consoleInputReadout')) LGMDM.dom.byId('consoleInputReadout').textContent = formatDb(input);
    if (LGMDM.dom.byId('consoleCompReadout')) LGMDM.dom.byId('consoleCompReadout').textContent = `${ct.toFixed(1)} dB · ${cr.toFixed(1)}:1`;
    if (LGMDM.dom.byId('consoleStereoReadout')) LGMDM.dom.byId('consoleStereoReadout').textContent = `${Math.round(sw * 100)}%`;
    if (LGMDM.dom.byId('consoleLimiterControlReadout')) LGMDM.dom.byId('consoleLimiterControlReadout').textContent = `${ceilingDb(ceil).toFixed(1)} dB`;
    if (LGMDM.dom.byId('consoleInputGr')) LGMDM.dom.byId('consoleInputGr').textContent = formatDb(input);
    if (LGMDM.dom.byId('consoleStereoGr')) LGMDM.dom.byId('consoleStereoGr').textContent = `WIDTH ${Math.round(sw * 100)}%`;
    if (LGMDM.dom.byId('consoleLimiterReadout')) LGMDM.dom.byId('consoleLimiterReadout').textContent = `CEILING ${ceilingDb(ceil).toFixed(1)}`;
    if (LGMDM.dom.byId('consoleCompGr')) LGMDM.dom.byId('consoleCompGr').textContent = `GR 0.0 dB`;
  }

  function updateStageCards() {
    document.querySelectorAll('.lg-stage-card').forEach(card => {
      const stage = card.dataset.stage;
      card.classList.toggle('bypassed', !!state.stageBypass[stage]);
      const em = card.querySelector('em');
      if (em) em.textContent = state.stageBypass[stage] ? 'BYPASS' : 'ACTIVE';
    });
  }

  function setAB(mode) {
    state.ab = mode;
    LGMDM.dom.byId('consoleABReadout')?.replaceChildren(document.createTextNode(mode === 'master' ? 'MASTER' : 'ORIGINAL'));
    LGMDM.dom.byId('consoleABMaster')?.classList.toggle('active', mode === 'master');
    LGMDM.dom.byId('consoleABOriginal')?.classList.toggle('active', mode === 'original');
    if (typeof window.LGMDM?.ab?.setMode === 'function') {
      try { window.LGMDM.ab.setMode(mode); return; } catch (_) {}
    }
    const audio = getPreviewAudio();
    if (audio) audio.dataset.abMode = mode;
  }

  function toggleAB() { setAB(state.ab === 'master' ? 'original' : 'master'); }

  function getPreviewAudio() {
    return document.querySelector('#previewAudioWrap audio, #mxrServerPreviewAudio');
  }

  function stopAllPlayback() {
    document.querySelectorAll('#previewAudioWrap audio, #mxrServerPreviewAudio').forEach((a) => {
      try { a.pause(); a.currentTime = 0; } catch (_) {}
    });
    window.LGMDM?.previewController?.stop?.();
    window.LGMDM?.ab?.stop?.();
    window.LGMDM?.mixer?.stopPreview?.(true);
    window.LGMDM?.reference?.stopRefPreview?.();
  }
  function formatTime(sec) {
    if (!Number.isFinite(sec)) return '--:--';
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = Math.floor(sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  function metricAmp(db, floor = -72) { return window.clamp01((Number(db ?? floor) - floor) / (0 - floor)); }

  function ensureScopeTap() {
    const tapApi = window.LGMDM?.proFeatures?.audioTap;
    if (!tapApi?.ensure) return null;
    try { return tapApi.ensure(); } catch (_) { return null; }
  }

  function isSignalPlaying() {
    const a = state.audio || getPreviewAudio();
    return !!(a && !a.paused && !a.ended);
  }

  function drawIdleWaveform(ctx, w, h, dpr, label) {
    ctx.fillStyle = 'rgba(116,230,255,.28)';
    ctx.font = `${Math.max(10, 11 * dpr)}px ${getComputedStyle(document.documentElement).getPropertyValue('--ui-font-mono') || 'monospace'}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.strokeStyle = 'rgba(116,230,255,.18)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  function drawWaveform() {
    const canvas = LGMDM.dom.byId('lgmdmWaveformCanvas'); if (!canvas) return;
    const rect = canvas.getBoundingClientRect(); const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(320, Math.floor(rect.width * dpr)), h = Math.max(120, Math.floor(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(116,230,255,.09)'; ctx.lineWidth = 1;
    for (let i = 1; i < 8; i++) { const y = h / 8 * i; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }
    const mid = h / 2;
    const playing = isSignalPlaying();
    const tap = playing ? ensureScopeTap() : null;
    const analyser = tap?.analyserWaterfall || null;
    if (!playing || !analyser) {
      drawIdleWaveform(ctx, w, h, dpr, 'Sin señal — reproducí el Preview');
      return;
    }
    if (!state.timeBuf || state.timeBuf.length !== analyser.fftSize) {
      state.timeBuf = new Float32Array(analyser.fftSize);
    }
    try { analyser.getFloatTimeDomainData(state.timeBuf); } catch (_) {
      drawIdleWaveform(ctx, w, h, dpr, 'Sin señal — reproducí el Preview');
      return;
    }
    const buf = state.timeBuf;
    const n = buf.length;
    // Envelope history from real peak/rms metrics (for the amber RMS trail)
    const m = state.metrics || {};
    const peakAmp = metricAmp(m.peak_db, -72);
    const rmsAmp = metricAmp(m.rms_db, -72);
    state.waveHistory.push({ peak: peakAmp, rms: rmsAmp, gr: Math.max(0, Math.min(1, Math.abs(Number(m.comp_gr_db ?? 0)) / 12)) });
    if (state.waveHistory.length > 90) state.waveHistory.shift();
    // Real waveform: map time-domain samples to canvas
    const grad = ctx.createLinearGradient(0,0,w,0);
    grad.addColorStop(0,'rgba(87,230,255,.35)'); grad.addColorStop(.5,'rgba(169,140,255,.95)'); grad.addColorStop(1,'rgba(87,230,255,.35)');
    ctx.strokeStyle = grad; ctx.lineWidth = Math.max(1, 1.4 * dpr);
    ctx.beginPath();
    const step = Math.max(1, Math.floor(n / w));
    for (let x = 0; x < w; x++) {
      const i = Math.min(n - 1, x * step);
      const v = Math.max(-1, Math.min(1, buf[i]));
      const y = mid - v * (h * 0.42);
      x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke();
    // Mirror half (filled envelope from |sample|)
    ctx.beginPath();
    for (let x = 0; x < w; x++) {
      const i = Math.min(n - 1, x * step);
      const a = Math.abs(buf[i]);
      const y = mid + a * (h * 0.42);
      x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = 'rgba(87,230,255,.28)'; ctx.lineWidth = Math.max(1, 1 * dpr); ctx.stroke();
    // Amber RMS history trail (real metrics, not fake texture)
    const hist = state.waveHistory;
    if (hist.length > 1) {
      ctx.beginPath();
      hist.forEach((item, i) => {
        const x = i / (hist.length - 1) * w;
        const y = mid - item.rms * h * 0.36;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.strokeStyle = 'rgba(255,202,101,.85)'; ctx.lineWidth = Math.max(1, 1 * dpr); ctx.stroke();
    }
  }

  function drawWaterfall() {
    const canvas = LGMDM.dom.byId('lgmdmWaterfallCanvas'); if (!canvas) return;
    const rect = canvas.getBoundingClientRect(); const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(320, Math.floor(rect.width * dpr)), h = Math.max(80, Math.floor(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const ctx = canvas.getContext('2d');
    const playing = isSignalPlaying();
    const tap = playing ? ensureScopeTap() : null;
    const an = tap?.analyserWaterfall;
    if (!playing || !an) {
      ctx.fillStyle = '#070c24';
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = 'rgba(116,230,255,.35)';
      ctx.font = `${Math.max(9, 10 * dpr)}px monospace`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('Sin señal', w / 2, h / 2);
      return;
    }
    if (!state.wfBuf || state.wfBuf.length !== an.frequencyBinCount) {
      state.wfBuf = new Uint8Array(an.frequencyBinCount);
    }
    try { an.getByteFrequencyData(state.wfBuf); } catch (_) { return; }
    const vr = window.LGMDM?.visualizerRender;
    if (vr?.drawWaterfallFrame) {
      vr.drawWaterfallFrame(canvas, ctx, null, state.wfBuf);
      return;
    }
    // Fallback: simple 1px scroll + colormap
    const img = ctx.getImageData(0, 0, w, h);
    ctx.putImageData(img, 0, 1);
    const bins = state.wfBuf.length;
    for (let x = 0; x < w; x++) {
      const binIdx = Math.min(bins - 1, Math.floor(Math.pow(x / w, 1.5) * (bins - 1)));
      const mag = state.wfBuf[binIdx] / 255;
      const r = Math.min(255, mag * 320) | 0;
      const g = Math.min(255, mag * 220) | 0;
      const b = Math.min(255, 40 + mag * 180) | 0;
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(x, 0, 1, 1);
    }
  }

  function drawConsoleSpectrum() {
    const canvas = LGMDM.dom.byId('lgmdmConsoleSpectrum'); if (!canvas) return;
    const m = state.metrics || {};
    // El backend emite varios formatos según el endpoint:
    //   1) analysis → m.spectrum_bands_db (28 objetos {freq_hz, db}) y m.fft_spectrum.magnitudes_db
    //   2) preview live → m.meters.spectrum.bands_db (32 bandas con freq_edges)
    //   3) master chain → m.chain_meters no tiene spectrum
    const s28 = Array.isArray(m.spectrum_bands_db) ? m.spectrum_bands_db : null;
    const fftMags = Array.isArray(m.fft_spectrum?.magnitudes_db) ? m.fft_spectrum.magnitudes_db : null;
    const s7 = (m.spectrum && typeof m.spectrum === 'object') ? m.spectrum : null;
    let bands = null; let edges = null;
    if (s28 && s28.length > 0 && typeof s28[0] === 'object' && 'db' in s28[0]) {
      bands = s28.map((b) => Number(b.db));
      edges = [s28[0].freq_hz * 0.9, ...s28.map((b) => Number(b.freq_hz))];
    } else if (fftMags) {
      bands = fftMags.map((v) => Number(v));
    } else if (s7) {
      const order = ['sub_bass', 'bass', 'low_mid', 'mid', 'upper_mid', 'presence', 'air'];
      bands = order.map((k) => Number(s7[k])).filter(Number.isFinite);
      edges = [20, 80, 250, 500, 2000, 4000, 8000];
    }
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(320, Math.floor(rect.width * dpr)), h = Math.max(120, Math.floor(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, w, h);
    if (!bands || bands.length === 0) return;
    const N = bands.length;
    const minDb = -90, maxDb = 0;
    const xForBand = (i) => {
      const lo = edges && edges[i] != null ? edges[i] : Math.pow(10, Math.log10(20) + (i / N) * (Math.log10(20000) - Math.log10(20)));
      const hi = edges && edges[i + 1] != null ? edges[i + 1] : Math.pow(10, Math.log10(20) + ((i + 1) / N) * (Math.log10(20000) - Math.log10(20)));
      const logLo = Math.log10(Math.max(20, lo)), logHi = Math.log10(Math.max(20, hi));
      const xLo = ((logLo - Math.log10(20)) / (Math.log10(20000) - Math.log10(20))) * w;
      const xHi = ((logHi - Math.log10(20)) / (Math.log10(20000) - Math.log10(20))) * w;
      return [xLo, xHi];
    };
    for (let i = 0; i < N; i++) {
      const v = Number(bands[i]);
      const [xLo, xHi] = xForBand(i);
      const barH = Number.isFinite(v) ? Math.max(2, ((v - minDb) / (maxDb - minDb)) * h) : 2;
      const xCenter = (xLo + xHi) / 2;
      const barW = Math.max(2, (xHi - xLo) * 0.85);
      const y = h - barH;
      const grad = ctx.createLinearGradient(0, y, 0, h);
      grad.addColorStop(0, 'rgba(125,232,255,0.95)');
      grad.addColorStop(1, 'rgba(87,180,255,0.55)');
      ctx.fillStyle = grad;
      ctx.fillRect(xCenter - barW / 2, y, barW, barH);
      ctx.fillStyle = 'rgba(125,232,255,0.45)';
      ctx.fillRect(xCenter - 0.5, 0, 1, h);
    }
  }

  function updateConsoleStereoVu() {
    const l = LGMDM.dom.byId('consoleMeterL'), r = LGMDM.dom.byId('consoleMeterR'); if(!l || !r) return;
    const m=state.metrics||{}; const peak=metricAmp(m.peak_db,-60); const corr=Math.max(-1,Math.min(1,Number(m.stereo_correlation ?? 1)));
    const spread=(1-Math.max(0,corr))*0.18;
    l.style.height=`${Math.max(3,Math.min(100,(peak*(1+spread))*100))}%`;
    r.style.height=`${Math.max(3,Math.min(100,(peak*(1-spread))*100))}%`;
    l.style.opacity = corr < 0 ? '1' : '.92'; r.style.opacity = corr < 0 ? '1' : '.92';
  }

  function setStatus(text, active=false) { LGMDM.dom.byId('consoleStatus')?.replaceChildren(document.createTextNode(text)); document.querySelector('.lg-status-dot')?.classList.toggle('active',active); }
  function syncTrackInfo() {
    const file = LGMDM.state?.selectedFile ?? null;
    if(!file){
      LGMDM.dom.byId('consoleTrackTitle')?.replaceChildren(document.createTextNode('Sin archivo cargado'));
      LGMDM.dom.byId('consoleTrackMeta')?.replaceChildren(document.createTextNode('Esperando señal'));
      return;
    }
    const title=file.name.replace(/\.[^/.]+$/,'');
    LGMDM.dom.byId('consoleTrackTitle')?.replaceChildren(document.createTextNode(title));
    LGMDM.dom.byId('consoleTrackMeta')?.replaceChildren(document.createTextNode(`${file.type||'audio'} · ${(file.size/1024/1024).toFixed(1)} MB`));
    setStatus('Audio cargado · listo para analizar',true);
  }
  // Re-entry guards (MX-13). Both syncMetersFromDom and syncChainMeters can be
  // invoked multiple times per frame: syncMetersFromDom from the rAF tick at
  // ~16ms when workspace=console, and syncChainMeters from the LGMDM.metrics
  // subscriber (which can fire every preview tick). JS is single-threaded, so
  // the worst case is duplicated work + "last-call-wins"; coalesce via guard +
  // queueMicrotask so we collapse bursts into one re-execution.
  let _metersSyncInFlight = false;
  let _metersSyncPending = false;
  let _lastMetrics = null;

  function syncMetersFromDom(){
    if (_metersSyncInFlight) { _metersSyncPending = true; return; }
    _metersSyncInFlight = true;
    try {
      const map=[['meterPeakReadout','consolePeak'],['meterLufsReadout','consoleLufs'],['meterTruePeakReadout','consoleTruePeak'],['meterRmsReadout','consoleRms'],['stereoMeterReadout','consoleCorr']];
      for(const [src,dst] of map){const a=LGMDM.dom.byId(src),b=LGMDM.dom.byId(dst);if(a&&b&&a.textContent)b.textContent=a.textContent.replace(/^corr:\s*/i,'');}
      updateConsoleStereoVu();
    } finally {
      _metersSyncInFlight = false;
      if (_metersSyncPending) {
        _metersSyncPending = false;
        queueMicrotask(syncMetersFromDom);
      }
    }
  }

  function syncChainMeters(metrics){
    if (metrics) _lastMetrics = metrics;
    if (_metersSyncInFlight) { _metersSyncPending = true; return; }
    _metersSyncInFlight = true;
    try {
      if (!_lastMetrics) return;
      const chain = _lastMetrics.chain_meters || _lastMetrics.chainMeters || {};
      const comp = chain.comp || _lastMetrics.comp_meters || {};
      const glue = chain.glue || _lastMetrics.glue_meters || {};
      const limiter = chain.limiter || _lastMetrics.limiter_meters || {};
      const compGr = Number(comp.gr_db ?? _lastMetrics.comp_gr_db ?? 0);
      const glueGr = Number(glue.gr_db ?? 0);
      const limGr = Number(limiter.gr_db ?? _lastMetrics.limiter_gr_db ?? 0);
      if (LGMDM.dom.byId('consoleCompGr')) LGMDM.dom.byId('consoleCompGr').textContent = `GR ${(Number.isFinite(compGr)?compGr:0).toFixed(1)} dB`;
      if (LGMDM.dom.byId('consoleLimiterGr')) LGMDM.dom.byId('consoleLimiterGr').textContent = `GR ${(Number.isFinite(limGr)?limGr:0).toFixed(1)} dB`;
      const glueReadout = LGMDM.dom.byId('consoleGlueGr'); if (glueReadout) glueReadout.textContent = `GR ${(Number.isFinite(glueGr)?glueGr:0).toFixed(1)} dB`;
      if (LGMDM.dom.byId('consoleOutputReadout')) LGMDM.dom.byId('consoleOutputReadout').textContent = _lastMetrics.output_lufs != null ? `${Number(_lastMetrics.output_lufs).toFixed(1)} LUFS` : (LGMDM.dom.byId('consoleLufs')?.textContent || '-∞ LUFS');
    } finally {
      _metersSyncInFlight = false;
      if (_metersSyncPending) {
        _metersSyncPending = false;
        queueMicrotask(() => syncChainMeters(null));
      }
    }
  }

  root.masterConsole.syncChainMeters = syncChainMeters;

        function scheduleConsolePreview(){
    if (state.applying) return;
    clearTimeout(root.masterConsole.previewTimer);
    root.masterConsole.previewTimer = setTimeout(() => {
      window.LGMDM?.previewController?.request?.();
    }, 350);
  }

  let wired = false;
  function wire(){
    if (wired) return;
    wired = true;
    mirror(...refs.input); mirror(...refs.compThreshold); mirror(...refs.compRatio); mirror(...refs.stereo); mirror(...refs.limiter);
    // F5.5 — ResizeObserver DPR-aware para waveform canvas.
    const _waveformCanvas = LGMDM.dom.byId('lgmdmWaveformCanvas');
    if (_waveformCanvas && typeof window.setupCanvasResize === 'function') {
      state._waveformCleanup = window.setupCanvasResize(_waveformCanvas, () => drawWaveform());
    }
    const _waterfallCanvas = LGMDM.dom.byId('lgmdmWaterfallCanvas');
    if (_waterfallCanvas && typeof window.setupCanvasResize === 'function') {
      state._waterfallCleanup = window.setupCanvasResize(_waterfallCanvas, () => drawWaterfall());
    }
    window.addEventListener('lgmdm:preview-ready', () => { ensureScopeTap(); });
    LGMDM.dom.byId('consoleAnalyzeBtn')?.addEventListener('click',()=>{LGMDM.dom.byId('btnAnalyze')?.click();setStatus('Analizando audio…',true);});
    LGMDM.dom.byId('consoleMasterBtn')?.addEventListener('click',()=>{LGMDM.dom.byId('btnMasterAsync')?.click();setStatus('Mastering en cola…',true);});
    LGMDM.dom.byId('consolePlayBtn')?.addEventListener('click',()=>{
      const audio=getPreviewAudio();
      if(!audio || !window.LGMDM?.previewController?.isReady?.()) {
        return setStatus('El Preview todavía no está listo: debe terminar el procesamiento del servidor.');
      }
      const pb = LGMDM.dom.byId('consolePlayBtn');
      if(audio.paused){audio.play().catch((e)=>setStatus('No se pudo reproducir el Preview: '+e.message));pb.textContent='❚❚';pb.setAttribute('aria-pressed','true');state.playing=true;state.start=performance.now();setStatus('Preview reproduciendo',true);}else{audio.pause();pb.textContent='▶';pb.setAttribute('aria-pressed','false');state.playing=false;setStatus('Preview en pausa');}
    });
    LGMDM.dom.byId('consoleStopBtn')?.addEventListener('click',()=>{
      stopAllPlayback();
      state.playing=false;LGMDM.dom.byId('consolePlayBtn').textContent='▶';setStatus('Preview detenido');
    });
    const livePreviewToggle = LGMDM.dom.byId('s-livepreview');
    if (livePreviewToggle) {
      const bind = window.LGMDM.ui.bindOnce;
      bind(livePreviewToggle, 'change', (ev) => {
        if (ev && ev.isTrusted === false) return;
        if (livePreviewToggle.checked && LGMDM.state?.selectedFile) {
          setStatus('Preview habilitado · procesando en servidor…', true);
          window.LGMDM?.previewController?.request?.();
        } else if (!livePreviewToggle.checked) {
          window.LGMDM?.previewController?.stop?.();
          setStatus('Preview deshabilitado');
        }
      }, 'server-preview-toggle-console');
    }
        LGMDM.dom.byId('consoleABMaster')?.addEventListener('click',()=>setAB('master')); LGMDM.dom.byId('consoleABOriginal')?.addEventListener('click',()=>setAB('original')); LGMDM.dom.byId('consoleABToggle')?.addEventListener('click',toggleAB);
    document.querySelectorAll('.lg-stage-card').forEach(btn=>btn.addEventListener('click',()=>toggleStage(btn.dataset.stage)));
    document.querySelectorAll('.lg-chain-node').forEach(btn=>btn.addEventListener('click',()=>document.querySelector(`.sidebar-tab[data-pane="${btn.dataset.pane}"]`)?.click()));
    LGMDM.dom.byId('consoleShowChain')?.addEventListener('click',()=>document.querySelector('.sidebar-tab[data-pane="pane-cadena"]')?.click());
    LGMDM.dom.byId('btnAnalyze')?.addEventListener('click',()=>setStatus('Analizando audio…',true)); LGMDM.dom.byId('btnMasterAsync')?.addEventListener('click',()=>setStatus('Mastering en cola…',true)); LGMDM.dom.byId('btnMasterSync')?.addEventListener('click',()=>setStatus('Mastering en proceso…',true));
    LGMDM.dom.byId('fileInput')?.addEventListener('change',syncTrackInfo);
    window.addEventListener('lgmdm:preview-state', (ev) => {
      const btn = LGMDM.dom.byId('consolePlayBtn');
      const detail = ev.detail || {};
      if (btn) btn.disabled = detail.state !== 'ready';
      if (detail.state === 'ready') setStatus('Preview completo listo para reproducir', true);
      else if (detail.state === 'processing') setStatus(detail.text || 'Procesando Preview en servidor…', true);
      else if (detail.state === 'disabled') setStatus(detail.text || 'Preview deshabilitado');
    });
    syncTrackInfo(); updateReadouts(); updateStageCards();
    const observer=new MutationObserver(syncTrackInfo); const fileName=LGMDM.dom.byId('fileName'); if(fileName)observer.observe(fileName,{childList:true,subtree:true,characterData:true});
    state._fileNameObserver = observer;
    const tick=()=>{
      if (!wired) return;
      if (window.LGMDM.utils.prefersReducedMotion()) {
        state.raf = 0;
        return;
      }
      const onConsole = document.body.dataset.workspace === "console";
      if(onConsole){ drawWaveform(); syncMetersFromDom(); drawConsoleSpectrum(); drawWaterfall(); }
      state.audio=getPreviewAudio();
      const audio=state.audio;
      if (audio && onConsole) {
        LGMDM.dom.byId('consoleTime').textContent = formatTime(audio.currentTime);
        LGMDM.dom.byId('consoleDuration').textContent = formatTime(audio.duration);
        const ph = LGMDM.dom.byId('consolePlayhead');
        if (Number.isFinite(audio.duration) && audio.duration > 0 && ph) ph.style.left = `${audio.currentTime / audio.duration * 100}%`;
      }
      state.raf = requestAnimationFrame(tick);
    };
    state.raf=requestAnimationFrame(tick);
    // Consume the shared Metrics Store instead of wrapping another producer.
    const metricsStore = window.LGMDM?.metrics;
    if (metricsStore) {
      state.unsubscribeMetrics?.();
      state.unsubscribeMetrics = metricsStore.subscribe(({ metrics }) => {
        state.metrics = metrics || null;
        root.masterConsole.syncChainMeters?.(metrics);
      });
    }
  }
  root.masterConsole.setStageBypass = (stage, bypass) => {
    if (!(stage in state.stageBypass)) throw new Error(`[Master Console] etapa desconocida: ${stage}`);
    state.stageBypass[stage] = Boolean(bypass);
    const related = {
      comp: ['s-thresh', 's-ratio'],
      stereo: ['s-width'],
      limiter: ['s-ceiling'],
    }[stage] || [];
    related.forEach((controlId) => {
      const el = LGMDM.dom.byId(controlId);
      if (!el) throw new Error(`[Master Console] falta control técnico #${controlId}`);
      if (state.stageBypass[stage]) {
        if (el.dataset.consoleSaved == null) el.dataset.consoleSaved = el.value;
        if (stage === 'comp') el.value = controlId === 's-ratio' ? '1' : '0';
        if (stage === 'stereo') el.value = '1';
        if (stage === 'limiter') el.value = '0.999';
      } else if (el.dataset.consoleSaved != null) {
        el.value = el.dataset.consoleSaved;
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
    updateReadouts(); updateStageCards();
    scheduleConsolePreview();
  };
  root.masterConsole.getChainOverrides = () => ({
    comp_bypass: !!state.stageBypass.comp,
    stereo_bypass: !!state.stageBypass.stereo,
    limiter_bypass: !!state.stageBypass.limiter,
  });
  root.masterConsole.setAB=setAB; root.masterConsole.toggleAB=toggleAB; root.masterConsole.schedulePreview=scheduleConsolePreview;
  root.masterConsole.stopAllPlayback=stopAllPlayback;
  root.console = root.masterConsole;
  function teardown(){
    if(state.raf){ cancelAnimationFrame(state.raf); state.raf=0; }
    if(state._fileNameObserver){ state._fileNameObserver.disconnect(); state._fileNameObserver=null; }
    if(state._waveformCleanup){ state._waveformCleanup(); state._waveformCleanup=null; }
    if(state._waterfallCleanup){ state._waterfallCleanup(); state._waterfallCleanup=null; }
    state.timeBuf = null; state.wfBuf = null; state.waveHistory = [];
    wired=false;
  }
  root.masterConsole.teardown=teardown;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',wire,{once:true});else wire();
})();
