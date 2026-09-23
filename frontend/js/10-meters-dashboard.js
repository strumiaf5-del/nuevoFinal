(function (global) {
  "use strict";
  const LGMDM = global.LGMDM = global.LGMDM || {};
// ============================================================
// 10-meters-dashboard.js — Dashboard, medidores en vivo, multiband GR/VU, espectrómetro
// ============================================================

// DOM cache centralizado en 00-api.js.
// ── Enlazar eventos de preview ──────────────────────────────
const previewTriggerIds = [
  "s-ingain",
  "s-peak",
  "s-uselufs",
  "s-lufstarget",
  "s-thresh",
  "s-ratio",
  "s-cattack",
  "s-crelease",
  "s-cmakeup",
  "s-comp-link",
  "s-oversample",
  "s-glue-bypass",
  "s-glue-thresh",
  "s-glue-ratio",
  "s-glue-attack",
  "s-glue-release",
  "s-glue-makeup",
  "s-glue-pdr",
  "s-glue-pdr-hold",
  "s-hp",
  "s-air",
  "s-shelf-freq",
  "s-lowshelf",
  "s-lowshelf-freq",
  "s-comp-pdr",
  "s-comp-pdr-hold",
  "s-mb-pdr",
  "s-mb-pdr-hold",
  "s-mscomp-pdr",
  "s-mscomp-pdr-hold",
  "s-mb-sw-lowx",
  "s-mb-sw-highx",
  "s-mb-sw-low",
  "s-mb-sw-mid",
  "s-mb-sw-high",
  "s-eq1freq",
  "s-eq1gain",
  "s-eq1q",
  "s-eq2freq",
  "s-eq2gain",
  "s-eq2q",
  "s-eq3freq",
  "s-eq3gain",
  "s-eq3q",
  "s-eq4freq",
  "s-eq4gain",
  "s-eq4q",
  "s-eq5freq",
  "s-eq5gain",
  "s-eq5q",
  "s-eq6freq",
  "s-eq6gain",
  "s-eq6q",
  "s-tatt",
  "s-tsus",
  "s-satdrive",
  "s-satmode",
  "s-satmix",
  "s-mgain",
  "s-sgain",
  "s-width",
  "s-enhancer",
  "s-haas",
  "s-bassmono",
  "s-rsize",
  "s-rwet",
  "s-ceiling",
  "s-lrelease",
  "s-format",
  "s-mb-lowx",
  "s-mb-highx",
  "s-mb-low-th",
  "s-mb-low-ratio",
  "s-mb-low-att",
  "s-mb-low-rel",
  "s-mb-low-mu",
  "s-mb-mid-th",
  "s-mb-mid-ratio",
  "s-mb-mid-att",
  "s-mb-mid-rel",
  "s-mb-mid-mu",
  "s-mb-high-th",
  "s-mb-high-ratio",
  "s-mb-high-att",
  "s-mb-high-rel",
  "s-mb-high-mu",
  "mb-bypass",
  "s-dyneq-bypass",
  "s-dyneq-freq",
  "s-dyneq-q",
  "s-dyneq-thresh",
  "s-dyneq-ratio",
  "s-dyneq-attack",
  "s-dyneq-release",
  "s-dyneq-maxred",
  "s-reso-bypass",
  "s-reso-freq",
  "s-reso-q",
  "s-reso-thresh",
  "s-reso-ratio",
  "s-reso-attack",
  "s-reso-release",
  "s-reso-maxred",
  "s-mono-freq",
  "s-mono-amount",
  "s-eq-mode",
  "s-lp-taps",
  "s-tonalbal-bypass",
  "s-tonalbal-amount",
  "s-tonalbal-boost",
  "s-tonalbal-cut",
  "s-tonalbal-bands",
  "parallelBypass",
  "parallelMix",
  "parallelThresh",
  "parallelRatio",
  "parallelAttack",
  "parallelRelease",
  "mb-stereo-bypass",
  "s-clip-bypass",
  "s-clip-mode",
  "s-clip-ceiling",
  "s-clip-drive",
  "s-lp-bypass",
  "s-lp-cutoff",
  "s-mseq-bypass",
  "s-mseq-mid-freq",
  "s-mseq-side-freq",
  "s-mscomp-bypass",
  "s-nr-bypass",
  "s-nr-strength",
  "s-nr-noise-sample-sec",
];

previewTriggerIds.forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  const evt = el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input";
  const bind = window.LGMDM.ui.bindOnce;
  bind(el, evt, () => window.LGMDM?.previewController?.request?.(), `preview-${evt}`);
});

// ── Dashboard ─────────────────────────────────────────────────
let dashboardWS = null,
  dashboardPollTimer = null;

function startDashboardPolling() {
  stopDashboard();
  dashboardPollTimer = setInterval(async () => {
    try {
      const res = await LGMDM.api.apiFetch(`${LGMDM.api.apiBase()}/dashboard`);
      if (res.status === 401 || res.status === 403) { stopDashboard(); return; }
    } catch (e) {}
  }, 5000);
}

function stopDashboard() {
  if (dashboardWS) {
    try {
      dashboardWS.close();
    } catch (e) {}
    dashboardWS = null;
  }
  if (dashboardPollTimer) {
    clearInterval(dashboardPollTimer);
    dashboardPollTimer = null;
  }
}

async function startDashboard() {
  stopDashboard();
  startDashboardPolling();
}

const dashboardBindOnce = window.LGMDM.ui.bindOnce;
dashboardBindOnce(window, 'lgmdm:authenticated', startDashboard, 'dashboard-authenticated');
startDashboard();

// ── Metrics Store → meters principales ───────────────────────
(function () {
  const store = window.LGMDM?.metrics;
  if (!store?.subscribe) return;
  const fill = (id, value, floor, ceiling = 0) => {
    const el = document.getElementById(id);
    if (!el) return;
    const n = Number(value);
    const pct = `${clamp01((n - floor) / (ceiling - floor)) * 100}%`;
    el.style.height = pct;
    el.style.width = '100%';
    if (Number.isFinite(n)) {
      el.setAttribute('aria-valuenow', String(Math.round(n * 10) / 10));
    }
  };
  const text = (id, value, suffix = '') => {
    const el = document.getElementById(id);
    if (!el) return;
    const n = Number(value);
    el.textContent = Number.isFinite(n) ? `${n.toFixed(1)}${suffix}` : `-∞${suffix}`;
  };
  const update = ({ metrics }) => {
    const m = metrics || {};
    const peak = Number(m.peak_db);
    const rms = Number(m.rms_db);
    const lufs = Number(m.lufs_momentary ?? m.lufs);
    const truePeak = Number(m.true_peak_db);
    const corr = Number(m.stereo_correlation);
    const mono = Number(m.mono_compatibility_db);
    fill('meterPeakFill', peak, -60, 0);
    fill('meterRmsFill', rms, -60, 0);
    fill('meterLufsFill', lufs, -40, 0);
    fill('meterTruePeakFill', truePeak, -60, 0);
    text('meterPeakReadout', peak, ' dB');
    text('meterRmsReadout', rms, ' dB');
    text('meterLufsReadout', lufs, ' LUFS');
    text('meterTruePeakReadout', truePeak, ' dBTP');
    // FIX 2: actualizar panel LUFS detallado (loudnessMeterWrap) cuando
    // llega metrics con lufs. El panel es estático en HTML; showLoudnessMeter
    // solo actualiza el número y la barra de progreso.
    if (typeof showLoudnessMeter === 'function' && Number.isFinite(lufs)) {
      showLoudnessMeter(lufs);
    }
    const stereoFill = document.getElementById('stereoMeterFill');
    if (stereoFill && Number.isFinite(corr)) {
      stereoFill.style.width = `${clamp01((corr + 1) / 2) * 100}%`;
      stereoFill.setAttribute('aria-valuenow', String(Math.round(corr * 100) / 100));
      stereoFill.setAttribute('aria-valuetext', `correlación ${corr.toFixed(2)}`);
    }
    if (Number.isFinite(corr)) {
      const el = document.getElementById('stereoMeterReadout');
      if (el) el.textContent = `corr: ${corr.toFixed(2)}`;
    }
    if (Number.isFinite(mono)) {
      const el = document.getElementById('monoCompatReadout');
      if (el) el.textContent = `mono: ${mono.toFixed(1)} dB`;
    }
    const bands = Array.isArray(m.spectrum) ? m.spectrum : [];
    const bandIds = ['sub','bass','lowmid','mid','highmid','air'];
    bandIds.forEach((id, i) => {
      const v = Number(bands[i]);
      const bar = document.getElementById(`fb-${id}`);
      const read = document.getElementById(`fbv-${id}`);
      if (bar && Number.isFinite(v)) {
        bar.style.width = `${clamp01((v + 80) / 80) * 100}%`;
        bar.setAttribute('aria-valuenow', String(Math.round(v)));
        bar.setAttribute('aria-valuetext', `${Math.round(v)} dB`);
      }
      if (read && Number.isFinite(v)) read.textContent = `${v.toFixed(0)} dB`;
    });

    // ── Reducción de ganancia multibanda + dinámica/paralela/glue ──────────
    // FIX A: backend envía toda la data de meters dentro de `m.meters.*`
    // (preview live) o campos planos (master job async). Unificamos ambas
    // rutas bajo `_chain`.
    const _chain = m.meters || m.chain_meters || m;
    const mb = _chain.mb || _chain.mb_meters || {};
    const compM = _chain.comp || _chain.comp_meters || {};
    const glueM = _chain.glue || _chain.glue_meters || {};
    const parM = _chain.parallel || _chain.parallel_meters || {};
    const msComp = _chain.ms_comp || _chain.ms_comp_meters || {};
    const deess = _chain.deess_meters || {};
    const reso = _chain.reso || _chain.reso_meters || {};
    const preLim = _chain.pre_limiter || {};
    const postLim = _chain.post_limiter || {};
    // GR section lives in Console and is always visible (no show/hide).
    const grSection = document.getElementById('mbGrSection');
    if (grSection) grSection.classList.remove('hidden-panel');

    const grBar = (barId, readId, grDb, { bypassLabel } = {}) => {
      const bar = document.getElementById(barId);
      const read = document.getElementById(readId);
      const v = Number(grDb);
      // gr_db en el backend es magnitud de reducción (0 = sin reducir, más
      // negativo/positivo = más reducción según el stage) — normalizamos a
      // "cuánto se comió" en dB positivos para la barra, tope visual 18dB.
      const reducedDb = Number.isFinite(v) ? Math.abs(v) : 0;
      if (bar) {
        bar.style.width = `${clamp01(reducedDb / 18) * 100}%`;
        bar.setAttribute('aria-valuenow', String(Math.round(reducedDb * 10) / 10));
        bar.setAttribute('aria-valuetext', `${reducedDb.toFixed(1)} dB`);
      }
      const text = Number.isFinite(v) ? `${reducedDb.toFixed(1)} dB` : (bypassLabel || '0.0 dB');
      if (read) {
        read.textContent = text;
        read.setAttribute?.('aria-valuenow', String(Math.round(reducedDb * 10) / 10));
        read.setAttribute?.('aria-valuetext', text);
      }
    };
    grBar('grBarLow', 'grReadLow', mb.low_gr_db);
    grBar('grBarMid', 'grReadMid', mb.mid_gr_db);
    grBar('grBarHigh', 'grReadHigh', mb.high_gr_db);
    grBar('grBarComp', 'grReadComp', compM.gr_db);
    grBar('grBarGlue', 'grReadGlue', glueM.bypass ? null : glueM.gr_db, { bypassLabel: 'bypass' });
    grBar('grBarParallel', 'grReadParallel', parM.bypass ? null : parM.gr_db, { bypassLabel: 'bypass' });

    // ── M/S Compressor ───────────────────────────────────────────────────
    // FIX B: ms_comp es anidado: {bypass, mid: {gr_db, ...}, side: {gr_db, ...}}
    grBar('grBarMsCompMid', 'grReadMsCompMid', msComp.bypass ? null : msComp.mid?.gr_db, { bypassLabel: 'bypass' });
    grBar('grBarMsCompSide', 'grReadMsCompSide', msComp.bypass ? null : msComp.side?.gr_db, { bypassLabel: 'bypass' });

    // ── De-esser + Dynamic EQ (resonancias) ────────────────────────────
    grBar('grBarDeess', 'grReadDeess', deess.bypass ? null : deess.gr_db, { bypassLabel: 'bypass' });
    grBar('grBarReso', 'grReadReso', reso.bypass ? null : reso.gr_db, { bypassLabel: 'bypass' });

    // ── Pre/Post-Limiter VU ─────────────────────────────────────────────
    const vuBar = (id, dbValue, suffix) => {
      const el = document.getElementById(id);
      if (!el) return;
      const v = Number(dbValue);
      if (Number.isFinite(v)) {
        el.textContent = `${v.toFixed(1)}${suffix}`;
        el.setAttribute('aria-valuenow', String(Math.round(v * 10) / 10));
        el.setAttribute('aria-valuetext', `${v.toFixed(1)}${suffix}`);
      } else {
        el.textContent = '--';
        el.setAttribute('aria-valuenow', '0');
        el.setAttribute('aria-valuetext', '--');
      }
    };
    vuBar('vuPreRms', preLim.rms_db, ' dB');
    vuBar('vuPrePeak', preLim.peak_db, ' dB');
    vuBar('vuPostRms', postLim.rms_db, ' dB');
    vuBar('vuPostPeak', postLim.peak_db, ' dB');
    vuBar('vuPostLufs', postLim.lufs, ' LUFS');

    // ── Meters summary (aria-live a 1Hz, solo en cruces de threshold) ──────
    updateMetersSummary(m);
  };

  // SR no debe recibir 60 updates/segundo del meter — solo anunciamos
  // cruces significativos (peak > -3 dBFS, true peak > -1 dBTP, cambio
  // grande de LUFS). Throttle: 1 Hz máx.
  const _summaryState = { lastText: '', lastTs: 0, lastPeak: -Infinity };
  function updateMetersSummary(m) {
    const now = performance.now();
    if (now - _summaryState.lastTs < 1000) return;
    const peak = Number(m.peak_db);
    const truePeak = Number(m.true_peak_db);
    const lufs = Number(m.lufs_momentary ?? m.lufs);
    let text = null;
    if (Number.isFinite(truePeak) && truePeak > -1) {
      text = `Atención: True Peak ${truePeak.toFixed(1)} dBTP cerca del clipping.`;
    } else if (Number.isFinite(peak) && peak > -3 && _summaryState.lastPeak <= -3) {
      text = `Peak subió a ${peak.toFixed(1)} dB.`;
    } else if (Number.isFinite(lufs) && Math.abs(lufs - (_summaryState.lastLufs ?? lufs)) > 2) {
      text = `Loudness momentáneo: ${lufs.toFixed(1)} LUFS.`;
    }
    _summaryState.lastTs = now;
    _summaryState.lastPeak = Number.isFinite(peak) ? peak : _summaryState.lastPeak;
    _summaryState.lastLufs = Number.isFinite(lufs) ? lufs : _summaryState.lastLufs;
    if (text && text !== _summaryState.lastText) {
      const el = document.getElementById('metersSummary');
      if (el) el.textContent = text;
      _summaryState.lastText = text;
    }
  }

  store.subscribe(update);

  // Bridge analysis-updated → metrics store (so meters show data after analysis)
  window.addEventListener('analysis-updated', (evt) => {
    const data = evt.detail;
    if (data && typeof store.publish === 'function') {
      try { store.publish(data, { source: 'analysis' }); } catch (_) {}
    }
  });
})();

// ── Live Meters ──────────────────────────────────────────────
function teardownLiveMeters() {
  const s = window.LGMDM?.state || {};
  if (s.metersRafId) {
    cancelAnimationFrame(s.metersRafId);
    s.metersRafId = null;
  }
  if (s.metersSourceNode) {
    try {
      s.metersSourceNode.stop();
    } catch (e) {}
    s.metersSourceNode = null;
  }
  if (s.metersAudioCtx) {
    try {
      s.metersAudioCtx.close();
    } catch (e) {}
    s.metersAudioCtx = null;
  }
}


  LGMDM.meters = LGMDM.meters || {};
  LGMDM.meters.stopDashboard = stopDashboard;
  LGMDM.meters.teardownLiveMeters = teardownLiveMeters;
})(window);
