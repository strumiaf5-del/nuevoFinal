// ============================================================
// 44-timeline-meters.js — Medidores en tiempo real 100% server-side
// Indexa un timeline pre-computado por el backend (compute_meters_timeline)
// usando audio.currentTime como índice. Sin AnalyserNode, sin biquads,
// sin getFloatFrequencyData. Los valores son exactos del backend.
// ============================================================
(function (global) {
  'use strict';
  const LG = global.LGMDM = global.LGMDM || {};
  const proFeatures = LG.proFeatures = LG.proFeatures || {};

  let timeline = null;
  let hopMs = 33;
  let chainSnapshot = null;
  let curves = null;
  let rafId = 0;
  let running = false;
  let idlePublished = false;

  function extractCurves(chain) {
    const out = {};
    if (!chain) return out;
    if (chain.comp && chain.comp.curve && chain.comp.curve_hop_ms) {
      out.comp = { curve: chain.comp.curve, hop: chain.comp.curve_hop_ms };
    }
    if (chain.mb && chain.mb.curve_hop_ms) {
      out.mb = {
        low: chain.mb.low_curve, mid: chain.mb.mid_curve, high: chain.mb.high_curve,
        hop: chain.mb.curve_hop_ms,
      };
    }
    if (chain.glue && chain.glue.curve && chain.glue.curve_hop_ms) {
      out.glue = { curve: chain.glue.curve, hop: chain.glue.curve_hop_ms };
    }
    if (chain.parallel && chain.parallel.curve && chain.parallel.curve_hop_ms) {
      out.parallel = { curve: chain.parallel.curve, hop: chain.parallel.curve_hop_ms };
    }
    if (chain.ms_comp) {
      if (chain.ms_comp.mid && chain.ms_comp.mid.curve && chain.ms_comp.mid.curve_hop_ms) {
        out.msMid = { curve: chain.ms_comp.mid.curve, hop: chain.ms_comp.mid.curve_hop_ms };
      }
      if (chain.ms_comp.side && chain.ms_comp.side.curve && chain.ms_comp.side.curve_hop_ms) {
        out.msSide = { curve: chain.ms_comp.side.curve, hop: chain.ms_comp.side.curve_hop_ms };
      }
    }
    return out;
  }

  function sampleCurve(entry, tSec) {
    if (!entry || !entry.curve || !entry.hop) return null;
    const idx = Math.floor((tSec * 1000) / entry.hop);
    const clamped = Math.max(0, Math.min(idx, entry.curve.length - 1));
    return Number(entry.curve[clamped]);
  }

  function flattenTelemetry(telemetry) {
    let flat = telemetry;
    if (telemetry.meters) flat = Object.assign({}, telemetry, telemetry.meters);
    if (telemetry.chain_meters) flat = Object.assign({}, flat, telemetry.chain_meters);
    const post = flat.post_limiter || (flat.chain_meters && flat.chain_meters.post_limiter);
    if (post) {
      if (post.peak_db != null && flat.peak_db == null) flat.peak_db = post.peak_db;
      if (post.rms_db != null && flat.rms_db == null) flat.rms_db = post.rms_db;
      if (post.lufs != null && flat.lufs == null) flat.lufs = post.lufs;
      if (post.stereo_correlation != null && flat.stereo_correlation == null) flat.stereo_correlation = post.stereo_correlation;
    }
    const aa = flat.analysis_after || (telemetry.analysis_after);
    if (aa) {
      if (aa.true_peak_db != null && flat.true_peak_db == null) flat.true_peak_db = aa.true_peak_db;
      if (aa.mono_compatibility_db != null && flat.mono_compatibility_db == null) flat.mono_compatibility_db = aa.mono_compatibility_db;
    }
    return flat;
  }

  function buildMetrics(block, tSec) {
    const base = chainSnapshot ? { ...chainSnapshot } : {};
    if (block) {
      if (Number.isFinite(block.peak_db)) base.peak_db = block.peak_db;
      if (Number.isFinite(block.rms_db)) base.rms_db = block.rms_db;
      if (Number.isFinite(block.lufs)) base.lufs_momentary = block.lufs;
      if (Number.isFinite(block.stereo_corr)) base.stereo_correlation = block.stereo_corr;
      if (Array.isArray(block.spectrum)) base.spectrum = block.spectrum;
    }

    if (curves && tSec != null) {
      const srcChain = (chainSnapshot && (chainSnapshot.chain_meters || chainSnapshot.meters)) || {};
      const chain = { ...srcChain };
      if (curves.comp) {
        const v = sampleCurve(curves.comp, tSec);
        if (v != null) chain.comp = { ...(chain.comp || {}), gr_db: v };
      }
      if (curves.glue) {
        const v = sampleCurve(curves.glue, tSec);
        if (v != null) chain.glue = { ...(chain.glue || {}), gr_db: v };
      }
      if (curves.parallel) {
        const v = sampleCurve(curves.parallel, tSec);
        if (v != null) chain.parallel = { ...(chain.parallel || {}), gr_db: v };
      }
      if (curves.mb) {
        const chain2 = chain.mb || {};
        const lv = sampleCurve({ curve: curves.mb.low, hop: curves.mb.hop }, tSec);
        const mv = sampleCurve({ curve: curves.mb.mid, hop: curves.mb.hop }, tSec);
        const hv = sampleCurve({ curve: curves.mb.high, hop: curves.mb.hop }, tSec);
        chain.mb = { ...chain2 };
        if (lv != null) chain.mb.low_gr_db = lv;
        if (mv != null) chain.mb.mid_gr_db = mv;
        if (hv != null) chain.mb.high_gr_db = hv;
      }
      if (curves.msMid) {
        const v = sampleCurve(curves.msMid, tSec);
        if (v != null) {
          chain.ms_comp = { ...(chain.ms_comp || {}) };
          chain.ms_comp.mid = { ...(chain.ms_comp.mid || {}), gr_db: v };
        }
      }
      if (curves.msSide) {
        const v = sampleCurve(curves.msSide, tSec);
        if (v != null) {
          chain.ms_comp = { ...(chain.ms_comp || {}) };
          chain.ms_comp.side = { ...(chain.ms_comp.side || {}), gr_db: v };
        }
      }
      if (chainSnapshot && chainSnapshot.chain_meters) {
        base.chain_meters = chain;
      } else {
        base.meters = chain;
      }
    }
    return base;
  }

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!running) return;

    const audio = document.querySelector('#previewAudioWrap audio[data-preview-ready="true"]')
               || document.querySelector('#previewAudioWrap audio');
    const playing = audio && !audio.paused && !audio.ended;

    if (!playing) {
      if (chainSnapshot && LG.metrics && !idlePublished) {
        try { LG.metrics.publish(buildMetrics(null, null), { source: 'server-timeline-idle' }); } catch (_) {}
        idlePublished = true;
      }
      return;
    }
    idlePublished = false;

    if (!timeline || !timeline.length) return;

    const tSec = Number(audio.currentTime) || 0;
    const idx = Math.max(0, Math.min(
      Math.floor((tSec * 1000) / hopMs),
      timeline.length - 1
    ));
    const block = timeline[idx];
    const metrics = buildMetrics(block, tSec);

    if (LG.metrics && typeof LG.metrics.publish === 'function') {
      try { LG.metrics.publish(metrics, { source: 'server-timeline' }); } catch (_) {}
    }
  }

  function start() {
    if (running) return;
    running = true;
    idlePublished = false;
    if (!rafId) rafId = requestAnimationFrame(tick);
  }

  function stop() {
    running = false;
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
  }

  function reset() {
    timeline = null;
    chainSnapshot = null;
    curves = null;
    stop();
  }

  global.addEventListener('lgmdm:preview-telemetry', (e) => {
    const d = e && e.detail;
    if (!d || !d.telemetry) return;
    const flat = flattenTelemetry(d.telemetry);
    chainSnapshot = flat;
    const chain = flat.chain_meters || flat.meters || flat;
    curves = extractCurves(chain);

    const tl = chain.meters_timeline || (d.telemetry.meters && d.telemetry.meters.meters_timeline);
    if (tl && tl.timeline && tl.timeline.length) {
      timeline = tl.timeline;
      hopMs = tl.hop_ms || 33;
      console.log('[44-timeline] meters_timeline cargada:', tl.n_blocks, 'bloques, hop=', hopMs, 'ms');
    } else {
      console.warn('[44-timeline] meters_timeline no encontrada en telemetry');
    }
    start();
  });

  global.addEventListener('lgmdm:preview-ready', (e) => {
    if (!e || !e.detail || !e.detail.ready) {
      chainSnapshot = null;
      curves = null;
      timeline = null;
      stop();
    } else {
      start();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { start(); }, { once: true });
  } else {
    start();
  }

  proFeatures.realtimeMeters = {
    start, stop, isRunning: () => running, reset,
    hasTimeline: () => !!(timeline && timeline.length),
  };
})(window);
