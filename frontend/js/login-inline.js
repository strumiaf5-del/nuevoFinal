    (function () {
      'use strict';

      const TOKEN_KEY = (typeof LGMDM !== 'undefined' && LGMDM.TOKEN_KEY) || 'master_auth_token';
      const USER_KEY  = 'master_auth_user';

      // 1. Detección automática del origen de la API
      // Prod: same-origin bajo /api (Caddy handle_path strippea el prefijo
      // y reverse-proxya al backend). duckdns.org está en el PSL →
      // subdominios serían cross-site y el browser bloquea third-party
      // cookies; same-origin lo evita. Dev localhost:8000 directo.
      function getApiBase() {
        try {
          const stored = localStorage.getItem('lgmdm_api_origin');
          if (stored) return stored;
        } catch (_) {}
        if (typeof location !== 'undefined' && (location.hostname === '127.0.0.1' || location.hostname === 'localhost')) {
          return `${location.protocol}//${location.hostname}:8000`;
        }
        return `${location.origin}/api`;
      }

      const API_BASE = getApiBase();

      function showMsg(id, text, type) {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = `auth-msg ${type}`;
        el.classList.remove('hidden');
      }

      function hideMsg(id) {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
      }

      function saveSession(token, user) {
        sessionStorage.setItem(TOKEN_KEY, token);
        sessionStorage.setItem(USER_KEY, JSON.stringify(user));
      }

      // 2. Si ya hay una sesión válida (cookie HttpOnly — el token de
      // sessionStorage solo sirve como hint para saltear el form), redirigir
      // directo a la consola. credentials:'include' es obligatorio: los
      // subdominios duckdns son cross-site (PSL) y sin include no viaja cookie.
      const existingToken = sessionStorage.getItem(TOKEN_KEY);
      if (existingToken) {
        fetch(`${API_BASE}/auth/me`, {
          credentials: 'include',
          headers: { 'Authorization': `Bearer ${existingToken}` }
        }).then(res => {
          if (res.ok) {
            window.location.replace('index.html');
          } else {
            sessionStorage.removeItem(TOKEN_KEY);
            sessionStorage.removeItem(USER_KEY);
          }
        }).catch(() => {});
      }

      // 3. Control de pestañas
      const tabLogin = document.getElementById('tab-login');
      const tabRegister = document.getElementById('tab-register');
      const formLogin = document.getElementById('form-login');
      const formRegister = document.getElementById('form-register');
      const formLoginReal = document.getElementById('form-login-real');
      const formRegisterReal = document.getElementById('form-register-real');

      tabLogin.addEventListener('click', () => {
        formLogin.classList.remove('hidden');
        formRegister.classList.add('hidden');
        tabLogin.classList.add('active');
        tabLogin.setAttribute('aria-selected', 'true');
        tabRegister.classList.remove('active');
        tabRegister.setAttribute('aria-selected', 'false');
        hideMsg('login-msg');
        document.getElementById('login-email').focus();
      });

      tabRegister.addEventListener('click', () => {
        formLogin.classList.add('hidden');
        formRegister.classList.remove('hidden');
        tabLogin.classList.remove('active');
        tabLogin.setAttribute('aria-selected', 'false');
        tabRegister.classList.add('active');
        tabRegister.setAttribute('aria-selected', 'true');
        hideMsg('reg-msg');
        document.getElementById('reg-name').focus();
      });

      // 4. Salto de teclado con Enter
      document.getElementById('login-email').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const pwd = document.getElementById('login-pwd');
          if (!pwd.value) {
            e.preventDefault();
            pwd.focus();
          }
        }
      });

      document.getElementById('reg-name').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          document.getElementById('reg-email').focus();
        }
      });

      document.getElementById('reg-email').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          document.getElementById('reg-pwd').focus();
        }
      });

      // 5. Envío de Login
      formLoginReal.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideMsg('login-msg');
        const email = document.getElementById('login-email').value.trim();
        const pwd = document.getElementById('login-pwd').value;
        const btn = document.getElementById('login-btn');

        if (!email || !pwd) {
          showMsg('login-msg', 'Completá todos los campos', 'error');
          return;
        }

        btn.disabled = true;
        btn.textContent = 'Ingresando…';

        try {
          const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password: pwd }),
            credentials: 'include'
          });

          const data = await res.json().catch(() => ({}));

          if (!res.ok) {
            throw new Error(data.detail || `Error de autenticación (HTTP ${res.status})`);
          }

          saveSession(data.access_token, data.user);
          btn.textContent = '✓ Redirigiendo a la consola…';
          window.location.replace('index.html');
        } catch (err) {
          showMsg('login-msg', err.message, 'error');
          btn.disabled = false;
          btn.textContent = 'Ingresar a la consola';
        }
      });

      // 6. Envío de Registro
      formRegisterReal.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideMsg('reg-msg');
        const name = document.getElementById('reg-name').value.trim();
        const email = document.getElementById('reg-email').value.trim();
        const pwd = document.getElementById('reg-pwd').value;
        const btn = document.getElementById('register-btn');

        if (!email || !pwd) {
          showMsg('reg-msg', 'Completá todos los campos', 'error');
          return;
        }

        btn.disabled = true;
        btn.textContent = 'Creando cuenta…';

        try {
          const res = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password: pwd, name }),
            credentials: 'include'
          });

          const data = await res.json().catch(() => ({}));

          if (!res.ok) {
            throw new Error(data.detail || `Error al crear cuenta (HTTP ${res.status})`);
          }

          showMsg('reg-msg', '✓ Cuenta creada con éxito. Aguardá la aprobación del administrador.', 'success');
          document.getElementById('reg-name').value = '';
          document.getElementById('reg-email').value = '';
          document.getElementById('reg-pwd').value = '';
        } catch (err) {
          showMsg('reg-msg', err.message, 'error');
        } finally {
          btn.disabled = false;
          btn.textContent = 'Crear cuenta';
        }
      });
    })();
