// ============================================================
// 00-api.js — API/HTTP/WebSocket helpers compartidos
// Debe cargarse antes de los demás módulos de frontend.
// ============================================================
(function (global) {
  'use strict';

  const TOKEN_KEY = 'master_auth_token';
  global.LGMDM = global.LGMDM || {};
  global.LGMDM.TOKEN_KEY = TOKEN_KEY; // Fuente única (00-auth.js la consume)
  const CSRF_META_SELECTOR = 'meta[name=\"lgmdm-csrf-token\"]';
  const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
  const DEFAULT_API_ORIGIN = (function() {
    try {
      const stored = localStorage.getItem('lgmdm_api_origin');
      if (stored) return stored;
    } catch (_) {}
    if (typeof location !== 'undefined' && (location.hostname === '127.0.0.1' || location.hostname === 'localhost')) {
      return `${location.protocol}//${location.hostname}:8000`;
    }
    return 'https://masteringstudio-api.duckdns.org';
  })();
  // Si ves errores tipo "Failed to load resource: ... 404" o "mixed content" o
  // URLs apuntando al host equivocado, ejecutá en la consola del navegador:
  //   localStorage.removeItem('lgmdm_api_origin'); location.reload();
  // Eso borra el override manual (si quedó uno stale) y vuelve al DEFAULT_API_ORIGIN.
  const ALLOWED_REMOTE_API_ORIGINS = new Set([
    'https://masteringstudio-api.duckdns.org',
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    DEFAULT_API_ORIGIN
  ]);
  const LGMDM = global.LGMDM = global.LGMDM || {};
  LGMDM.api = LGMDM.api || {};

  function normalizeApiOrigin(value) {
    const raw = String(value || '').trim() || DEFAULT_API_ORIGIN;
    let url;
    try {
      url = new URL(raw, global.location.origin);
    } catch (_) {
      throw new Error('La URL de la API no es válida');
    }
    if (!['http:', 'https:'].includes(url.protocol)) {
      throw new Error('La URL de la API debe usar http:// o https://');
    }
    url.username = '';
    url.password = '';
    url.hash = '';
    url.search = '';
    url.pathname = url.pathname.replace(/\/$/, '');
    const origin = url.origin;
    if (origin !== global.location.origin && !ALLOWED_REMOTE_API_ORIGINS.has(origin)) {
      throw new Error('Origen de API no permitido por la política de seguridad de LGMDM');
    }
    return origin;
  }

  function apiBase() {
    return normalizeApiOrigin(DEFAULT_API_ORIGIN);
  }

  function authToken() {
    // SEC-A-01: el token JWT vive en cookie HttpOnly (server-controlled).
    // JS no puede leerla (intencional — evita exfiltración via XSS).
    // Devolvemos string vacío: apiFetch manda solo la cookie via el browser,
    // no el header Authorization. Si el caller necesita Authorization header
    // explícito (p.ej. WS ticket exchange), debe poblarlo manualmente.
    return '';
  }

  function csrfToken() {
    const meta = document.querySelector(CSRF_META_SELECTOR);
    const metaValue = meta?.content?.trim();
    if (metaValue) return metaValue;
    try { return sessionStorage.getItem('lgmdm.csrf-token') || ''; } catch (_) { return ''; }
  }

  function authHeaders(extra, method = 'GET') {
    // SEC-A-01: el browser manda la cookie HttpOnly 'lgmdm_access_token'
    // automáticamente — no seteamos Authorization header. CSRF token sigue
    // siendo necesario para métodos no-safe como defensa contra CSRF sobre
    // cookies autenticadas.
    const headers = { ...(extra || {}) };
    const normalizedMethod = String(method || 'GET').toUpperCase();
    if (!SAFE_METHODS.has(normalizedMethod)) {
      const csrf = csrfToken();
      if (csrf && !headers['X-CSRF-Token'] && !headers['x-csrf-token']) headers['X-CSRF-Token'] = csrf;
    }
    return headers;
  }

  function apiUrl(path = '') {
    if (!path) return apiBase();
    return `${apiBase()}${path.startsWith('/') ? path : `/${path}`}`;
  }

  function wsUrl(path = '') {
    const url = new URL(apiBase());
    if (!['http:', 'https:'].includes(url.protocol)) {
      throw new Error('La URL de la API debe usar http:// o https://');
    }
    const base = `${url.protocol === 'https:' ? 'wss' : 'ws'}://${url.host}`;
    return `${base}${path.startsWith('/') ? path : `/${path}`}`;
  }

  async function wsAuthHandle(path = '') {
    // SEC-A-01: la sesión vive en cookie HttpOnly — JS no puede verificarla
    // client-side. Pedimos el ticket igual; el server responde 401/403 si no
    // hay sesión y eso se mapea a AUTH_REQUIRED para los callers.
    const url = wsUrl(path);
    const res = await apiFetch('/auth/ws-ticket');
    if (res.status === 401 || res.status === 403) {
      const err = new Error('Sesión requerida para autorizar WebSocket');
      err.code = 'AUTH_REQUIRED';
      throw err;
    }
    if (!res.ok) throw new Error(`No se pudo autorizar WebSocket (${res.status})`);
    const data = await res.json();
    if (!data.token || typeof data.token !== 'string') {
      throw new Error('El servidor no devolvió un ticket WebSocket válido');
    }
    // Mandamos el ticket por Sec-WebSocket-Protocol (slot "lgmdm-ws-ticket.<token>")
    // y NO por ?token= — el server hace eco de "lgmdm-ws-ticket" en
    // accept(subprotocol=...) y extrae el token del segundo slot. El token
    // nunca aparece en la URL: no queda en logs de proxies ni en history.
    return {
      url,
      protocols: ['lgmdm-ws-ticket', data.token],
      token: data.token,
    };
  }

  async function wsAuthUrl(path = '') {
    const { url, token } = await wsAuthHandle(path);
    const target = new URL(url);
    target.searchParams.set('token', token);
    return target.toString();
  }

  const rawFetch = global.fetch.bind(global);

  function resolveApiTarget(path) {
    const raw = String(path ?? '');
    const target = /^https?:\/\//i.test(raw) ? new URL(raw) : new URL(apiUrl(raw));
    const baseOrigin = apiBase();
    if (target.origin !== baseOrigin) {
      throw new Error('Destino API fuera del origen permitido');
    }
    if (!['http:', 'https:'].includes(target.protocol)) {
      throw new Error('Protocolo API no permitido');
    }
    return target.toString();
  }

  const RETRYABLE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'PUT']);
  const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
  const DEFAULT_MAX_RETRIES = 2;
  const DEFAULT_TIMEOUT_MS = 30000;

  function retryAfterMs(response, fallbackMs) {
    const raw = response.headers.get('retry-after');
    if (!raw) return fallbackMs;
    const seconds = Number(raw);
    if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 30000);
    const date = Date.parse(raw);
    if (Number.isFinite(date)) return Math.max(0, Math.min(date - Date.now(), 30000));
    return fallbackMs;
  }

  function isFormDataBody(body) {
    return typeof FormData !== 'undefined' && body instanceof FormData;
  }

  async function apiFetch(path, options = {}) {
    const opts = { ...options };
    // SEC-A-01: la auth vive en cookie HttpOnly de masteringstudio-api.
    // Cross-origin (subdominios duckdns son cross-site por PSL) el fetch
    // default credentials:'same-origin' NO manda cookies — hace falta
    // 'include' explícito en CADA request.
    if (opts.credentials === undefined) opts.credentials = 'include';
    const method = String(opts.method || 'GET').toUpperCase();
    const externalSignal = opts.signal || null;
    const timeoutOption = Object.prototype.hasOwnProperty.call(opts, 'timeout') ? opts.timeout : undefined;
    const maxRetries = Math.max(0, Number(opts.maxRetries ?? DEFAULT_MAX_RETRIES) || 0);
    const retryNonIdempotent = opts.retryNonIdempotent === true;
    const retryableMethod = RETRYABLE_METHODS.has(method) || retryNonIdempotent;
    const timeoutMs = timeoutOption === undefined
      ? (isFormDataBody(opts.body) ? 0 : DEFAULT_TIMEOUT_MS)
      : Math.max(0, Number(timeoutOption) || 0);

    delete opts.timeout;
    delete opts.maxRetries;
    delete opts.retryNonIdempotent;
    opts.headers = authHeaders(opts.headers, method);
    const target = resolveApiTarget(path);
    let lastError = null;

    for (let attempt = 0; attempt <= (retryableMethod ? maxRetries : 0); attempt += 1) {
      // P2 modernization: AbortSignal.timeout + AbortSignal.any reemplazan el
      // AbortController manual + setTimeout. La razón y la limpieza del
      // timer las maneja el browser — menos código, menos bugs.
      const timeoutSignal = timeoutMs > 0 ? AbortSignal.timeout(timeoutMs) : null;
      const signal = (timeoutSignal && externalSignal) ? AbortSignal.any([timeoutSignal, externalSignal])
                   : timeoutSignal || externalSignal || null;

      try {
        const requestOptions = { ...opts };
        if (signal) requestOptions.signal = signal;

        const response = await rawFetch(target, requestOptions);
        if (!RETRYABLE_STATUSES.has(response.status) || attempt >= maxRetries || !retryableMethod) {
          return response;
        }

        const delayMs = retryAfterMs(response, 500 * (2 ** attempt));
        await new Promise((resolve) => global.setTimeout(resolve, delayMs));
      } catch (error) {
        lastError = error;
        if (externalSignal?.aborted) throw error;
        const retryableError = retryableMethod && attempt < maxRetries && error?.name !== 'AbortError' && error?.name !== 'TimeoutError';
        if (!retryableError) throw error;
        await new Promise((resolve) => global.setTimeout(resolve, 500 * (2 ** attempt)));
      }
    }

    throw lastError || new Error('La solicitud HTTP agotó los reintentos permitidos');
  }

  function filenameFromResponse(res, fallback = 'lgmdm-download') {
    const cd = res.headers.get('content-disposition') || '';
    const utf = cd.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf) { try { return decodeURIComponent(utf[1].trim().replace(/^"|"$/g, '')); } catch (_) {} }
    const plain = cd.match(/filename="?([^";]+)"?/i);
    return plain ? plain[1].trim() : fallback;
  }

  async function downloadAuthenticated(path, options = {}) {
    const { filename = 'lgmdm-download', notify = true, ...fetchOptions } = options || {};
    const res = await apiFetch(path, fetchOptions);
    if (res.status === 401 || res.status === 403) {
      window.dispatchEvent(new CustomEvent('lgmdm:auth-required', { detail: { status: res.status, path: String(path) } }));
      let detail = 'Sesión expirada. Iniciá sesión nuevamente para descargar.';
      try { const data = await res.clone().json(); detail = String(data.detail || '').replace(/[<>]/g, '') || detail; } catch (_) {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    if (!res.ok) {
      let detail = `Error de descarga (HTTP ${res.status})`;
      try { const data = await res.clone().json(); detail = String(data.detail || '').replace(/[<>]/g, '') || detail; } catch (_) {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filenameFromResponse(res, filename);
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    return { response: res, blob };
  }

  async function request(method, path, options = {}) {
    return apiFetch(path, { ...options, method: String(method).toUpperCase() });
  }

  const client = {
    request,
    get: (path, options) => request('GET', path, options),
    post: (path, options) => request('POST', path, options),
    put: (path, options) => request('PUT', path, options),
    patch: (path, options) => request('PATCH', path, options),
    delete: (path, options) => request('DELETE', path, options),
  };

  Object.assign(LGMDM.api, { apiBase, apiUrl, wsUrl, wsAuthHandle, wsAuthUrl, authToken, csrfToken, authHeaders, apiFetch, downloadAuthenticated, resolveApiTarget, request, client });

  const domCache = new Map();
  function cachedEl(id) {
    if (domCache.has(id)) return domCache.get(id);
    const el = document.getElementById(id);
    if (el) domCache.set(id, el);
    return el;
  }
  function invalidateCachedEl(...ids) { ids.forEach(id => domCache.delete(id)); }
  const _byIdMissingLogged = new Set();
  function byId(id) {
    const node = document.getElementById(id);
    if (!node && typeof console !== 'undefined' && !_byIdMissingLogged.has(id)) {
      _byIdMissingLogged.add(id);
      console.debug(`[LGMDM.dom] #${id} not found`);
    }
    return node;
  }
  function requireById(id, owner = '') {
    const node = document.getElementById(id);
    if (!node) {
      const err = new Error(`[LGMDM DOM CONTRACT] ${owner || 'unknown'}: #${id} is required but missing`);
      console.error(err);
      throw err;
    }
    return node;
  }
  LGMDM.dom = LGMDM.dom || {};
  LGMDM.dom.cachedEl = cachedEl;
  LGMDM.dom.invalidateCachedEl = invalidateCachedEl;
  LGMDM.dom.byId = byId;
  LGMDM.dom.requireById = requireById;
})(window);
