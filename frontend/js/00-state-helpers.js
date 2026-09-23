// ============================================================
// 00-state-helpers.js — Getters compartidos de state + freq transforms
// Audit C+D — centraliza wrappers duplicados entre 4 archivos.
// Carga: entre 00-state.js y 01-state.js (los widgets lo consumen).
// ============================================================
// API pública:
//   window.LGMDM.stateHelpers.getSelectedFile()   → file|null
//   window.LGMDM.stateHelpers.getLastAnalysis()    → analysis|null
//   window.LGMDM.freqHelpers.freqToX(f, left, width, LOG_FMIN, LOG_FMAX) → x
//   window.LGMDM.freqHelpers.dbToY(db, top, height, DMIN, DMAX) → y
//   window.LGMDM.freqHelpers.xToFreq(x, left, width, LOG_FMIN, LOG_FMAX) → freq
// ============================================================

(function (global) {
  "use strict";

  const ns = (global.LGMDM = global.LGMDM || {});

  // ── State getters (Audit C) ────────────────────────────────────────────────
  // Antes: 4 archivos (20-pro-upgrades, 29-analysis-view, 34-premium-suite,
  // y el call site original en 01-state.js) declaraban local wrappers
  // `getSelectedFile = () => LGMDM.state?.getSelectedFile?.() ?? null`
  // y `getLastAnalysis = () => ...`. Esta versión es la única fuente.
  const stateHelpers = {
    getSelectedFile() {
      return (global.LGMDM && global.LGMDM.state && typeof global.LGMDM.state.getSelectedFile === 'function')
        ? global.LGMDM.state.getSelectedFile()
        : null;
    },
    getLastAnalysis() {
      return (global.LGMDM && global.LGMDM.state && typeof global.LGMDM.state.getLastAnalysis === 'function')
        ? global.LGMDM.state.getLastAnalysis()
        : null;
    },
  };

  // ── Freq/db → canvas coords (Audit D) ─────────────────────────────────────
  // Antes: 3 widgets (reference-match, saturation, spectral-tilt)
  // declaraban wrappers `_xFreq/_yDb/_freqFromX` de 1 línea cada uno
  // sobre los helpers globales (00-utils.js:26-55). Esta versión los
  // reexpone bajo un namespace descubrible.
  const freqHelpers = {
    freqToX(f, left, width, LOG_FMIN, LOG_FMAX) {
      return global.xFromFreq ? global.xFromFreq(f, left, width, LOG_FMIN, LOG_FMAX) : left;
    },
    dbToY(db, top, height, DMIN, DMAX) {
      return global.yFromDb ? global.yFromDb(db, top, height, DMIN, DMAX) : top;
    },
    xToFreq(x, left, width, LOG_FMIN, LOG_FMAX) {
      return global.freqFromX ? global.freqFromX(x, left, width, LOG_FMIN, LOG_FMAX) : 20;
    },
  };

  ns.stateHelpers = stateHelpers;
  ns.freqHelpers = freqHelpers;
})(window);
