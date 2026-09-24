// ============================================================
// pro-features/premium-utils.js — Math + persistence helpers
// F3.8 — Extraído de 34-premium-suite.js (split monolito)
// ============================================================
// API pública (expone via window.LGMDM.premiumUtils):
//   - pearsonCorrelation(x, y) → number (-1..1)
//   - loadDemaskSettings(target) → mutates target.demask (clamped 0..100)
//   - saveDemaskSettings(source) → stringifies source.demask to localStorage
//
// Carga: ANTES de 34-premium-suite.js. premium-suite consume estos
// helpers via window.LGMDM.premiumUtils.*.
// ============================================================

(function (global) {
  "use strict";

  const ns = (global.LGMDM = global.LGMDM || {}).premiumUtils = (global.LGMDM && global.LGMDM.premiumUtils) || {};
  const STORAGE_KEY_DEMASK = 'lg_premium_demask_settings';

  // Correlación de Pearson entre dos arrays. Usada por el goniometro
  // (F5.9 — halo pulsante cuando |corr| > 0.85) y por la pestaña ABX.
  function pearsonCorrelation(x, y) {
    const n = Math.min(x.length, y.length);
    if (n < 2) return 0;
    let sx = 0, sy = 0, sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      const xi = x[i], yi = y[i];
      sx += xi; sy += yi;
      sxy += xi * yi;
      sxx += xi * xi;
      syy += yi * yi;
    }
    const denom = Math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy));
    if (!Number.isFinite(denom) || denom === 0) return 0;
    return (n * sxy - sx * sy) / denom;
  }

  // Carga settings de de-mask desde localStorage. Acepta formato
  // consolidado ({kickDepth, voxDepth}) o legacy (claves separadas
  // lg_demask_kick/lg_demask_vox). Mutates target.demask en site.
  function loadDemaskSettings(target) {
    try {
      const raw = localStorage.getItem(STORAGE_KEY_DEMASK);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Number.isFinite(Number(parsed.kickDepth))) {
          target.demask.kickDepth = Math.max(0, Math.min(100, Number(parsed.kickDepth)));
        }
        if (Number.isFinite(Number(parsed.voxDepth))) {
          target.demask.voxDepth = Math.max(0, Math.min(100, Number(parsed.voxDepth)));
        }
      } else {
        const k = localStorage.getItem('lg_demask_kick');
        const v = localStorage.getItem('lg_demask_vox');
        if (Number.isFinite(Number(k))) target.demask.kickDepth = Math.max(0, Math.min(100, Number(k)));
        if (Number.isFinite(Number(v))) target.demask.voxDepth = Math.max(0, Math.min(100, Number(v)));
      }
    } catch (_) {}
  }

  function saveDemaskSettings(source) {
    try {
      localStorage.setItem(STORAGE_KEY_DEMASK, JSON.stringify(source.demask));
    } catch (_) {}
  }

  Object.assign(ns, { pearsonCorrelation, loadDemaskSettings, saveDemaskSettings });
})(window);
