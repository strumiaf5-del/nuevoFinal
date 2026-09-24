# AGENTS.md — LGMDM frontend

Frontend estático (HTML/CSS/JS, sin bundler) en `frontend/`. Sin build step, sin package manager, sin tests, sin dev server dedicado: los archivos se sirven tal cual. Este repo no cubre el backend (vive en `../backend/`); toda la info de abajo asume que solo vas a tocar el frontend.

## Layout

- `frontend/index.html` — SPA monolítica (~1990 líneas), incluye header, sidebar, paneles y todos los `<script defer>` y `<link rel="stylesheet">`.
- `frontend/login.html` — pantalla de auth.
- `frontend/css/base/` — `reset.css`, `tokens.css`, `themes.css`, `themes-professional.css`. Orden importa: tokens → reset → themes.
- `frontend/css/components/_index.css` — "module manifest" con `@import` ordenados: `base → utilities → buttons → forms → header → sidebar → panels → content-area → meters → dashboard → preview → ai-panel → workflow`. NO importes los archivos de `components/` individualmente; importá desde `_index.css`.
- `frontend/css/layout/` — `layout-shell.css`, `responsive.css`.
- `frontend/css/skin/themes-professional-skin.css` — overrides del tema pro.
- `frontend/css/widgets/` — `chain-family-tabs.css`, `pro-insert-rack.css`, `pro-widgets-v2.css`. En `index.html` se cargan con `media="print" onload="this.media='all'"` (carga no-bloqueante).
- `frontend/css/_archive/` — LEGACY. NO importar ni referenciar. Quedó de un monolítico anterior; los de `components/` lo reemplazaron.
- `frontend/js/<NN>-*.js` — scripts numerados y cargados (NN = orden, 00..43). Convención: `00-*` son core, el resto features en orden de dependencia.
- `frontend/js/pro-features/*.js` — 14 widgets premium; cada uno se registra en `34-premium-suite.js` (ver más abajo).
- `frontend/js/_archive/` — LEGACY huérfano movido acá. 30 archivos NO se cargan desde `index.html`. Ver sección "Legacy huérfano".

## Carga de scripts en index.html — el ORDEN IMPORTA

`index.html` carga ~64 `<script defer>` en este orden (resumido; ver el archivo para el detalle):

1. JSON `<script id="sliders-meta">` — DEBE ir antes de `02-sliders-ui.js` (lo lee directo).
2. Core `00-*` en este orden: `00-utils.js`, `00-ui-core.js`, `00-modal-helper.js`, `00-dom-safety.js`, `00-storage.js`, `00-api.js`, `00-theme-manager.js`, `00-audio-engine.js`, `00-auth.js`, `00-compat.js`. Todos se registran en `window.LGMDM` y los features los consumen.
3. `01-state.js` — singleton de state global, expone `window.LGMDM.state`. Va después del core `00-*`.
4. Features numerados (`02-*` .. `43-*`) en orden.
5. `34-premium-suite.js` registra las clases de los widgets pro.
6. `40-tab-*.js`, `41-tab-*.js`, `42-tab-*.js`, `43-tab-*.js` van DESPUÉS de `34-premium-suite.js` (cada uno tiene un `// Carga: tras 34-premium-suite.js` arriba del archivo).
7. Widgets pro (`js/pro-features/*.js`) y `js/pro-insert-rack.js` van al final.

Reordenar o saltearse un core `00-*` rompe el resto. Si agregás un script nuevo, mantené el patrón numérico.

## Estado global y namespace

- Todo se monta en `window.LGMDM` (los core `00-*` con `(function(global){ ... })(window)` + `global.LGMDM = global.LGMDM || {}`).
- `window.LGMDM.config` — valores compartidos congelados (`maxFileMb`, `previewDurationSec`). Fuente única: `00-config.js`. NO hardcodear esos números en otros scripts.
- `window.LGMDM.state` — singleton mutable (auth, parámetros, jobs). Bridges cross-script documentados en `01-state.js`.
- Auth: token y user en `sessionStorage` con keys `master_auth_token` y `master_auth_user` (`00-auth.js`). Cambiarlas rompe otras pantallas.

## Estilos — convenciones

- Inline `style="..."` + CSS custom properties `--ui-*` están permitidos a propósito. El CSP del backend deja `style-src 'unsafe-inline'` específicamente por esto (ver `backend/app.py`).
- Para valores reusables usá `var(--ui-*)`, no repitas literales. Los tokens base están en `css/base/tokens.css`.
- Temas: las variables `--ui-*` se redefinen en `css/base/themes.css` y `themes-professional.css`. Para cambiar colores de un widget usá la variable, no un literal.

## Widgets pro — cómo agregar uno nuevo

1. Crear `frontend/js/pro-features/<nombre>-widget.js` siguiendo el patrón de los existentes (factory + clase).
2. Agregar el `<script defer src="js/pro-features/<nombre>-widget.js">` en `index.html` al final, en la sección de pro-features.
3. Registrar la clase en el registry de `34-premium-suite.js` (ver el `console.warn` que tira cuando una clase pedida no está registrada).

## Legacy huérfano — NO editar esperando que tenga efecto

Los 30 archivos legacy fueron movidos a `frontend/js/_archive/` y NO se cargan desde `index.html`:

- `00-*` huérfanos: `00-error-handler.js`, `00-memory-cleanup.js`, `00-observability.js`.
- Sin numerar: `17-keyboard-shortcuts.js`, `33-studio-controller.js`, `ai-assistant-ux.js`, `analysis-view.js`, `api.js`, `auth.js`, `confirm-panel.js`, `console-resize.js`, `file.js`, `flex-layout.js`, `header-resize.js`, `library-picker.js`, `main.js`, `make-resizable.js`, `master-console.js`, `mastering.js`, `meters-dashboard.js`, `params.js`, `preview-controller.js`, `reference-mastering.js`, `spectrum-controller.js`, `state.js`, `storage.js`, `studio-controller.js`, `system-status.js`, `visualizers.js`, `workspace-tabs.js`.

La app usa las versiones numeradas equivalentes (`10-meters-dashboard.js`, `15-master-console.js`, `30-preview-controller.js`, etc.). Verificar con `grep -E 'js/[^"]+\.js' frontend/index.html | sort -u` y comparar contra `ls frontend/js/*.js`.

## Telemetría / medidores en vivo (flujo real)

- Endpoint correcto: `GET /preview/meters/{source_id}` (NO existe `/preview/telemetry`).
- `30-preview-controller.js` publica en `LGMDM.metrics` (store en `30-metrics-store.js`).
- `10-meters-dashboard.js` subscribe y pinta Peak/RMS/LUFS/TruePeak/Stereo + bandas + GR multibanda (`#mbGrSection`, siempre visible en Console).
- Signal Scope: `15-master-console.js` dibuja waveform REAL desde `AnalyserNode` (vía `35-audio-tap.js` → `proFeatures.audioTap.ensure()`) y waterfall scrolling (`#lgmdmWaterfallCanvas`) usando `LGMDM.visualizerRender.drawWaterfallFrame`.

## Servir el frontend

No hay dev server dedicado. El frontend se sirve aparte del backend (el backend solo expone la API). El endpoint de producción es `https://masteringstudio.duckdns.org`, configurado vía `FRONTEND_ORIGIN` en `backend/.env`. Para desarrollo local usá cualquier servidor estático (`python -m http.server` desde `frontend/`, o el que prefieras).

## Lo que NO existe acá

Sin tests, sin linter, sin formatter, sin bundler, sin `package.json`, sin TypeScript, sin pre-commit, sin Docker. Si necesitás alguno, lo estás agregando desde cero.
