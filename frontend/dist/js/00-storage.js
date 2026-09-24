(function(global){
  'use strict';
  const LG = global.LGMDM = global.LGMDM || {};
  const storage = LG.storage = LG.storage || {};
  const persist = LG.persist = LG.persist || {};

  function makeBackend(area) {
    return {
      get(key, fallback = null) {
        try {
          const value = area.getItem(String(key));
          return value == null ? fallback : value;
        } catch (_) { return fallback; }
      },
      set(key, value) {
        try {
          area.setItem(String(key), String(value));
          return true;
        } catch (_) { return false; }
      },
      remove(key) {
        try { area.removeItem(String(key)); return true; }
        catch (_) { return false; }
      },
      getJSON(key, fallback = null) {
        const raw = this.get(key, null);
        if (raw == null) return fallback;
        try { return JSON.parse(raw); }
        catch (_) { return fallback; }
      },
      setJSON(key, value) {
        try { return this.set(key, JSON.stringify(value)); }
        catch (_) { return false; }
      },
    };
  }

  // localStorage (persiste entre sesiones; cuota ~5MB por origin)
  const local = makeBackend(global.localStorage);
  // sessionStorage (vive solo en la pestaña actual; cuota ~5MB)
  const session = global.sessionStorage ? makeBackend(global.sessionStorage) : local;

  persist.local = local;
  persist.session = session;

  // Compat: LG.storage apunta al backend localStorage (uso histórico).
  Object.assign(storage, { get: local.get, set: local.set, remove: local.remove, getJSON: local.getJSON, setJSON: local.setJSON });
})(window);
