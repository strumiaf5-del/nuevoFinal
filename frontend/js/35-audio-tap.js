// ============================================================
// 35-audio-tap.js — Audio routing compartido para Pro Suite
// ============================================================
// Extraído de 34-premium-suite.js (Fase 5 — consolidación).
// Provee un único Splitter/AnalyserNode conectado a la fuente
// de audio activa (mixer master o <audio> del preview), que
// reutilizan goniómetro, waterfall, aurora y multibanda.
//
// API pública:
//   LGMDM.proFeatures.audioTap.ensure()
//   LGMDM.proFeatures.audioTap.teardown()
//   LGMDM.proFeatures.audioTap.bandSpecs   // [{id, label, freq, q}, …]
// ============================================================

(function (global) {
  "use strict";
  const LG = global.LGMDM = global.LGMDM || {};
  const proFeatures = LG.proFeatures = LG.proFeatures || {};

  const _audioTap = {
    ctx: null,
    source: null,
    splitter: null,
    masterOut: null,
    sourceType: null,
    sourceEl: null,
    mediaSource: null,
    analyserGonioL: null,
    analyserGonioR: null,
    analyserWaterfall: null,
    analyserAurora: null,
    bandAnalysers: [],
    bandFilters: [],
    ready: false,
  };

  const BAND_SPECS = [
    { id: 'lowMid',  label: 'Low-Mid (200 Hz – 2 kHz)', freq: 632,   q: 0.7 },
    { id: 'highMid', label: 'High-Mid (2 kHz – 6 kHz)', freq: 3464,  q: 1.0 },
    { id: 'air',     label: 'Air (> 6 kHz)',            freq: 9798,  q: 1.2 },
  ];

  function ensureAudioTap() {
    if (_audioTap.ready) return _audioTap;

    const mixerMaster = LG?.mixerEngine?.previewEngine?.masterGain;
    const audioEl = document.querySelector('#previewAudioWrap audio[data-preview-ready="true"]')
                  || document.querySelector('#previewAudioWrap audio')
                  || document.querySelector('#mxrServerPreviewAudio');
    if (!mixerMaster && !audioEl) return null;

    const ctx = (LG.audio && typeof LG.audio.getContext === 'function')
      ? LG.audio.getContext()
      : null;
    if (!ctx) return null;

    let source = null;
    let sourceType = null;
    let masterOut = null;
    let mediaSource = null;

    if (mixerMaster && mixerMaster.context === ctx && mixerMaster.context.state !== 'closed') {
      source = mixerMaster;
      sourceType = 'mixer';
    } else if (audioEl) {
      try {
        mediaSource = ctx.createMediaElementSource(audioEl);
        masterOut = ctx.createGain();
        masterOut.gain.value = 1;
        mediaSource.connect(masterOut);
        masterOut.connect(ctx.destination);
        source = mediaSource;
        sourceType = 'media-element';
      } catch (_) {
        return null;
      }
    }

    const splitter = ctx.createChannelSplitter(2);
    source.connect(splitter);

    const analyserGonioL = ctx.createAnalyser();
    analyserGonioL.fftSize = 1024;
    analyserGonioL.smoothingTimeConstant = 0;
    const analyserGonioR = ctx.createAnalyser();
    analyserGonioR.fftSize = 1024;
    analyserGonioR.smoothingTimeConstant = 0;
    splitter.connect(analyserGonioL, 0);
    splitter.connect(analyserGonioR, 1);

    const analyserWaterfall = ctx.createAnalyser();
    analyserWaterfall.fftSize = 2048;
    analyserWaterfall.smoothingTimeConstant = 0.65;
    splitter.connect(analyserWaterfall, 0);

    const analyserAurora = ctx.createAnalyser();
    analyserAurora.fftSize = 2048;
    analyserAurora.smoothingTimeConstant = 0.78;
    splitter.connect(analyserAurora, 0);

    const bandAnalysers = [];
    const bandFilters = [];
    for (const spec of BAND_SPECS) {
      const fL = ctx.createBiquadFilter();
      fL.type = 'bandpass';
      fL.frequency.value = spec.freq;
      fL.Q.value = spec.q;
      const fR = ctx.createBiquadFilter();
      fR.type = 'bandpass';
      fR.frequency.value = spec.freq;
      fR.Q.value = spec.q;
      splitter.connect(fL, 0);
      splitter.connect(fR, 1);
      const aL = ctx.createAnalyser();
      aL.fftSize = 512;
      aL.smoothingTimeConstant = 0;
      const aR = ctx.createAnalyser();
      aR.fftSize = 512;
      aR.smoothingTimeConstant = 0;
      fL.connect(aL);
      fR.connect(aR);
      bandAnalysers.push([aL, aR]);
      bandFilters.push([fL, fR]);
    }

    Object.assign(_audioTap, {
      ctx, source, splitter, masterOut, mediaSource,
      sourceType,
      sourceEl: sourceType === 'media-element' ? source.mediaElement : null,
      analyserGonioL, analyserGonioR, analyserWaterfall, analyserAurora,
      bandAnalysers, bandFilters,
      ready: true,
    });
    LG.state = LG.state || {};
    LG.state.audio = LG.state.audio || {};
    LG.state.audio.tap = _audioTap;
    return _audioTap;
  }

  function teardownAudioTap() {
    if (!_audioTap || !_audioTap.ready) return;
    const safe = (node) => { try { node && node.disconnect && node.disconnect(); } catch (_) {} };
    safe(_audioTap.splitter);
    safe(_audioTap.analyserGonioL);
    safe(_audioTap.analyserGonioR);
    safe(_audioTap.analyserWaterfall);
    safe(_audioTap.analyserAurora);
    (_audioTap.bandAnalysers || []).forEach((pair) => pair.forEach(safe));
    (_audioTap.bandFilters || []).forEach((pair) => pair.forEach(safe));
    if (_audioTap.sourceType === 'media-element') {
      safe(_audioTap.masterOut);
      safe(_audioTap.mediaSource);
    }
    Object.assign(_audioTap, {
      ready: false,
      ctx: null,
      source: null,
      splitter: null,
      masterOut: null,
      mediaSource: null,
      sourceType: null,
      sourceEl: null,
      analyserGonioL: null,
      analyserGonioR: null,
      analyserWaterfall: null,
      analyserAurora: null,
      bandAnalysers: [],
      bandFilters: [],
    });
    if (LG.state?.audio?.tap === _audioTap) LG.state.audio.tap = null;
  }

  proFeatures.audioTap = {
    ensure: ensureAudioTap,
    teardown: teardownAudioTap,
    bandSpecs: BAND_SPECS,
  };
})(window);
