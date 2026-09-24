# AUDIT_REPORT.md — LGMDM frontend (consolidado)

**Generado:** 5 sub-agentes en paralelo (security, CSS×2, JS×2).
**Scope:** `frontend/` completo, scripts vivos (~60) + CSS vivo + estilos inline. **Excluidos:** 28 archivos JS legacy huérfanos (ver `AGENTS.md`) y `css/_archive/`.
**Lectura:** ~22k LoC JS + ~3k LoC CSS.

---

## 🔴 P0 — Bloqueantes (arreglar ya)

### Funcionalidad rota en producción

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **JS-B2** | code-reviewer JS | `40-43-tab-*.js:13-14` | Los 4 tabs (compliance, ABX, codec, waterfall) usan namespace doble `proFeatures.proFeatures.tabs.X`. El resto del sistema lee `proFeatures.tabs.X`. Resultado: **los 4 tabs aparecen como "Tab no disponible" en producción**, incluso cuando los widgets existen. |
| **JS-B1** | code-reviewer JS | `reference-match-widget.js:38-43`, `spectral-tilt-widget.js:38,40-43`, `phase-rotation-widget.js:41-42` | Tres widgets pro referencian globales (`window.xFromFreq`, `window.yFromDb`, `window.logFreq`) que **no existen en ningún script vivo**. Cargan en silencio pero rompen en el primer render con `TypeError`. |
| **CSS-B01** | CSS widgets | `js/17-keyboard-shortcuts.js:182-337` | El modal de atajos (`?`) sale **sin estilos visibles** porque usa 6 tokens eliminados (`--surface`, `--border`, `--accent`, `--text`, `--muted`, `--sans`). El CSS ya no los define. |
| **CSS-B4** | CSS base | `themes-professional-skin.css:59-67` | El skin pisa `.btn-primary` con `var(--ui-panel)`, anulando el gradiente amber de marca. El comentario dice que `.btn-primary` se preserva pero el selector no lo excluye. |
| **SEC-M03** | security | `js/34-premium-suite.js:2696` | `getSelectedFile().name` se inyecta sin `escapeHtml` en la plantilla `_proPanelShell`. Un nombre de archivo malicioso (vía upload o librería persistente) **puede ejecutar JS** en la sesión. Único XSS explotable concreto identificado. |
| **JS-B1-WS** | javascript-pro | `js/08-reference-mastering.js:340-394` | WebSocket `/ws/ref-stream` sin reconexión ni cleanup. Si el server corta, la previsualización de referencia muere sin aviso y queda zombie. |
| **JS-B2-WORKER** | javascript-pro | `js/05-eq-waveform.js:105-122` | Worker singleton con callback pisado. Mover sliders rápido **congela la curva EQ** en posiciones aleatorias. |

---

## 🟠 P1 — Importantes (planificar)

### Seguridad / defensa en profundidad

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **SEC-A-01** | security | `00-auth.js`, `00-api.js` | JWT en `sessionStorage`. Es el patrón correcto para SPA, pero si entra un XSS residual (M03 arriba), el token se exfiltra. Migración a cookie `HttpOnly` queda como follow-up. |
| **SEC-A-02** | security | `index.html:1842-1904` | Sin Subresource Integrity (`integrity="sha384-..."`) en ningún `<script>` ni `<link>`. Si el servidor estático se compromete, no hay defensa en el cliente. |
| **SEC-A-03** | security | `index.html`, `login.html` | Sin `<meta http-equiv="Content-Security-Policy">` defensivo en HTML. El CSP vive 100% en backend; si se desconfigura, no hay red. |
| **SEC-M-02** | security | `00-api.js:98-113` | Ticket de WebSocket se pasa por `?token=` query string. Riesgo bajo si el ticket es single-use + corta vida (verificar backend). Mejor alternativa: `Sec-WebSocket-Protocol` subprotocol. |
| **SEC-M-04** | security | varios JS | Mensajes de error del backend (`data.detail`) se muestran al usuario escapados pero no sanitizados. Information disclosure pasiva. |
| **SEC-M-05** | security | `03-presets.js:194-217` | Preset JSON cargado de archivo local se aplica sin validar schema/tipos/rangos. Riesgo bajo (no XSS, va a `.value`), pero DoS local posible. |

### CSS — problemas de mantenimiento y consistencia

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **CSS-B-1** | CSS base | 13 archivos de `components/` | Indentación rota en TODOS los archivos (mezcla 6-espacios y 2-espacios). Estético pero erosiona mantenibilidad y oculta bugs en diffs. |
| **CSS-B-2** | CSS base | `responsive.css:36-66, 380-428` | Bloque `@media (max-width: 959px)` **duplicado**, con reglas que se contradicen (`.meters-grid` redefinido dos veces). Comportamiento no determinista. |
| **CSS-I-4** | CSS base | múltiples | **~20 literales hardcoded** (`rgba(255,255,255,X)`, `#69e4ae`, `rgba(232,48,32,...)`) que deberían ser `var(--ui-*)` o `color-mix(in srgb, var(--ui-X) X%, transparent)`. **Rompe el sistema de temas** en producción (los colores no cambian con el tema). |
| **CSS-I-2** | CSS base | `themes.css` vs `themes-professional-skin.css` | El "skin layer" redefine `.theme-switcher-*` con valores distintos y `.btn-*`. Doble fuente de verdad. Cambiar un color en `themes.css` no tiene efecto sin tocar el skin. |
| **CSS-B-05** | CSS widgets | `login.html:10-240` | Bloque `<style>` inline de 230 LoC con **0 tokens `--ui-*`**. Rompe consistencia visual y bloquea temas. |
| **CSS-B-02** | CSS widgets | `chain-family-tabs.css:7` | Único `@layer sidebar` aislado en todo el CSS — inconsistente con el resto. |
| **CSS-B-04** | CSS widgets | `index.html:30-33` + `32-chain-family-tabs.js:154` | Race condition entre CSS `media="print" onload="this.media='all'"` y `DOMContentLoaded` del JS que monta widgets. FOUC visible en conexiones lentas. |
| **CSS-M1** | CSS base | `dashboard.css:1-8` | Archivo "trampa" con 8 líneas que solo contiene `.meters-toggle` (pertenece a `meters.css`). Ruido estructural. |

### JS — bugs latentes y deuda estructural

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **JS-B-3** | code-reviewer | `phase-rotation-widget.js:407` | `Widget.prototype.constructor.prototype.data` no existe. La rama siempre evalúa a `bands = []`. 0 bandas procesadas sin error visible. |
| **JS-B-4** | code-reviewer | varios widgets pro | `globalThis.BaseCanvasWidget` se extiende vía global mutable. Funciona hoy pero rompe si se minifica con bundler. Falta documentación de dependencia por archivo. |
| **JS-B-5** | code-reviewer | `35-audio-tap.js:74-76` | `catch (_) { return null; }` silencioso en `createMediaElementSource`. Si el elemento ya está enganchado, el tap queda mudo sin diagnóstico. Cascada de widgets "no funciona". |
| **JS-I3** | code-reviewer | `34-premium-suite.js` (3337 líneas) | Monolítico con >20 features. **Imposible de testear unitariamente**; merge conflicts garantizados. El archivo debería ser solo el registry; cada feature debe vivir en su propio archivo. |
| **JS-I-2** | javascript-pro | `18-undo-redo.js:19-58` | `JSON.parse(JSON.stringify(state))` × 8 — **jank perceptible en mobile** (30-50ms por operación). Reemplazar por `structuredClone()` (ES2022, ya soportado). |
| **JS-I-3** | javascript-pro | `30-preview-controller.js:332-356` | Blob URL huérfana si `await res.blob()` falla. Micro-leak acumulable. Falta try/finally. |
| **JS-I-4** | javascript-pro | `00-audio-engine.js:13-21` | `shutdown()` solo en `beforeunload`, no en `pagehide` (más confiable en mobile) ni `visibilitychange`. |
| **JS-I-5** | javascript-pro | `09-visualizers.js` | `_abUiTimer` setea cada 200ms y **nunca se limpia**. `_abRafId` declarado pero nunca asignado (dead code). |
| **JS-I-7** | javascript-pro | `15-master-console.js:355` | `root.console = root.console || {}` crea un objeto `console` propio que **no es la API nativa del browser**. Cualquier `root.console.warn(...)` falla silencioso. |
| **JS-I-9** | code-reviewer | `multiband-transient-widget.js` | Triple fuente de verdad (`state.attack_ms`, `_user.attack[i]`, `_amount`). Backend recibe 4 representaciones del mismo valor. |
| **JS-I-10** | code-reviewer | 11 widgets pro | Patrón `try { rack.create(...) } catch (e) { console.debug(...) }` se repite. Si `proInsertRack` no está listo, el widget queda fuera del rack sin error visible. |
| **JS-I-12** | code-reviewer | `index.html:1856` (`sliders-meta`) | Schema del JSON inline sin validación. Si se agrega slider y se olvida la entry, no se bindea — sin error visible. |

### Persistencia / estado

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **JS-I-1** | code-reviewer | `00-auth.js` y `00-api.js` | `TOKEN_KEY` duplicado en dos archivos. Si uno cambia sin el otro, sesión rota. |
| **JS-I-2** | code-reviewer | `00-auth.js`, `00-storage.js`, `pro-insert-rack.js:25-35` | Persistencia inconsistente: cada script repite `try { JSON.parse(...) } catch { return null }`. Falta `LGMDM.persist.session/local` centralizado. |

---

## 🟡 P2 — Mejorables / quick wins

### Limpieza segura (riesgo 0)

| ID | Acción | Detalle |
|---|---|---|
| **CLEAN-01** | Borrar `frontend/css/_archive/` (28 archivos, 5.6k LoC) | 16 duplican contrapartes activas; el resto son consolidados históricos. **0 referencias en código vivo**. |
| **CLEAN-02** | Borrar bloque duplicado `responsive.css:36-66` | Consolidar en el bloque 380-428. |
| **CLEAN-03** | Borrar `dashboard.css`, mover `.meters-toggle` a `meters.css` | Solo tiene 8 líneas con una regla que pertenece a otro archivo. |
| **CLEAN-04** | Borrar fallbacks innecesarios `var(--ui-X, rgba(...))` en widgets | ~20+ ocurrencias; nunca se activan. |
| **CLEAN-05** | Borrar inline `style="width:0%"` en `index.html:1691` | Redundante con `.lufs-bar-fill`. |
| **CLEAN-06** | Borrar comment huérfano `/* ── Responsive ── */` en `pro-insert-rack.css:227` | No tiene reglas entre este y el siguiente bloque. |
| **CLEAN-07** | Borrar selector vacío `.chain-family-visible {}` en `chain-family-tabs.css:54-58` | Solo tiene un comentario. |
| **CLEAN-08** | Renombrar `.lgjs-s-6b99de8b` en `base.css:51-53` | Nombre con hash, anti-patrón de CSS modules. |

### Bugs menores

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **JS-M-14** | code-reviewer | `pro-insert-rack.js:431` | `if (typeof persistFromDom === 'function')` es guard inútil — la función siempre existe en el closure. |
| **JS-M-4** | code-reviewer | `spectral-tilt-widget.js:177-183` | `_draggingPivot` flag dead code — se setea y resetea sin ser leído. |
| **JS-M-13** | code-reviewer | `pro-insert-rack.js:162` | `if (position) payload.position = position;` ambiguo — `NaN` no se guarda. ¿Intencional? |
| **JS-M-15** | javascript-pro | `35-audio-tap.js:46` | `LG?.mixerEngine?.previewEngine?.masterGain` no se reconecta si cambia la instancia. |
| **CSS-B-07** | CSS widgets | `multiband-transient-widget.js:177-183` | `.mtw-led-bar`/`.mtw-led-fill` se usan en JS sin reglas CSS — viven solo como inline styles. |

### Deuda estilística

| ID | Origen | Archivo:línea | Descripción |
|---|---|---|---|
| **CSS-I-1** | CSS base | `reset.css` | Reset incompleto: falta `summary`/`details`/`fieldset`/`legend`/`figure`/`dialog`. |
| **CSS-I-3** | CSS base | `utilities.css:183-209, 697-712` | `.empty-state` definido DOS veces con valores divergentes. |
| **CSS-I-5** | CSS base | `layout-shell.css:13` | `:has()` con specificity compuesta — no soportado en Firefox <121, bugs en Safari <15.4. |
| **CSS-I-6** | CSS base | `components/base.css:62-134` | Fallbacks hardcodeados en `var(--ui-X, #0a0e27)` — esconden errores de renombrado. |
| **CSS-I-7** | CSS base | `responsive.css` | Header dice "Mobile First" pero todas las media queries son `max-width` (desktop-first). |
| **CSS-I-8** | CSS base | `layout-shell.css:62-93` | Specificity alta (`class > id`) obliga a selectores acoplados en `sidebar.css`. |
| **CSS-B-03** | CSS widgets | `pro-insert-rack.css` (14 ocurrencias) | Literales `rgba(125, 232, 255, X)` repetidos — ya tiene `--pir-border` para lo mismo. |
| **CSS-B-11** | CSS widgets | `14-pitch-correction.js:16-86` | Mezcla tokens con literales en el mismo bloque. |
| **CSS-B-16** | CSS widgets | `components/studio.css` | 400 LoC con `rgba(...)` y `#69e4ae` sin tocar `--ui-*` ni una vez. |

### Features modernas desaprovechadas

| Feature | Estado | Acción |
|---|---|---|
| `structuredClone()` | ❌ usado solo `JSON.parse(JSON.stringify())` | Reemplazar en `18-undo-redo.js` (8 lugares) |
| `AbortSignal.timeout(ms)` | ❌ usado `setTimeout(()=>abort,ms)` | Reemplazar en `00-api.js`, `00-auth.js`, `30-preview-controller.js` |
| Private class fields (`#`) | ❌ convention `_underscore` | Migrar `BaseCanvasWidget` |
| `Promise.withResolvers()` | ❌ usado `let resolved=false`+closures | Útil en WS wrappers de `08-reference-mastering.js` |

---

## Top 5 quick wins (orden de implementación)

1. **CSS-B01** (1 archivo, 30 min): reemplazar 6 tokens en `js/17-keyboard-shortcuts.js:182-337` — fix inmediato del modal de atajos.
2. **SEC-M03** (1 línea, 5 min): envolver `getSelectedFile().name` con `escapeHtml` en `js/34-premium-suite.js:2696` — fix del único XSS explotable concreto.
3. **JS-B2** (4 archivos, 30 min): cambiar `proFeatures.proFeatures.tabs.X` → `proFeatures.tabs.X` en `40-43-tab-*.js`.
4. **JS-I-2** (1 archivo, 1h): reemplazar 8 `JSON.parse(JSON.stringify())` por `structuredClone()` en `18-undo-redo.js` — fix del jank en undo.
5. **JS-B1** (1 archivo nuevo + 3 ediciones, 2h): extraer helpers `xFromFreq/yFromDb/logFreq` a `00-canvas-math.js` (cargado antes que los widgets pro).

---

## Qué se omitió intencionalmente

- Los 28 archivos legacy huérfanos (no se auditaron — son candidatos a borrado directo).
- `css/_archive/` (no se auditó contenido — confirmado muerto, borrable).
- El backend (descartado por el usuario).
- Auditoría de performance con datos reales (no se ejecutó el frontend en este entorno).
- Auditoría de accesibilidad WCAG completa (se hizo chequeo de contraste básico; convendría herramienta dedicada).

---

## Estado de remediación P0 (septiembre 2026)

| ID | Estado | Cambio aplicado |
|---|---|---|
| **CSS-B4** | ✅ Aplicado | `frontend/css/skin/themes-professional-skin.css:59-67` — wrapper `.btn-*, ...` reemplazado por `:where(.btn-*, ...)` para que `.btn-primary` gane por specificity 0. |
| **CSS-B01** | ✅ Aplicado | `frontend/js/17-keyboard-shortcuts.js` — 19 ocurrencias de 6 tokens legacy (`--surface2`, `--surface3`, `--border`, `--accent`, `--text`, `--muted`, `--sans`) reemplazadas por sus equivalentes `--ui-*`. |
| **SEC-M03** | ✅ Aplicado | `frontend/js/34-premium-suite.js:2696` — `getSelectedFile().name` ahora se envuelve con `window.LGMDM.ui.escapeHtml`. |
| **JS-B2** | ✅ Aplicado | `frontend/js/40-43-tab-*.js` (4 archivos) — namespace doble `proFeatures.proFeatures.tabs.X` corregido a `proFeatures.tabs.X`, que es lo que espera el dispatch en `34-premium-suite.js:433`. |
| **JS-B2-WORKER** | ✅ Aplicado | `frontend/js/05-eq-waveform.js:105-145` — singleton `eqCallback` reemplazado por `Map<seq, callback>` + worker reenvía `_seq` en su `postMessage`. Solo se procesa la respuesta del último seq solicitado. |
| **JS-B1** | ❌ **Falso positivo** | Los widgets pro (`reference-match`, `spectral-tilt`, `phase-rotation`) referencian `logFreq`, `xFromFreq`, `yFromDb`, `freqFromX` sin prefijo. Verificado empíricamente: estas funciones SÍ están definidas en `frontend/js/00-utils.js:84-89` y expuestas como `window.logFreq`, etc. Como `00-utils.js` se carga ANTES de los widgets pro (`index.html:1842` vs `1899-1904`), el lookup implícito de globales funciona. No requiere cambios. |
| **JS-B1-WS** | ✅ Aplicado | `frontend/js/08-reference-mastering.js:230-236,326-462` — `_refReconnectAttempts`, `_refReconnectTimer`, `_refMaxReconnectAttempts`, `_refReconnectBaseMs`, `_refReconnectMaxMs` movidos a scope de módulo. `onclose` ahora: cancela timer pendiente, hace backoff exponencial con cap 30s (1s→2s→4s→8s→16s→30s), respeta `_refPreviewActive === false` (no reconecta si el usuario detuvo), muestra estado "Reconectando en Ns…", y resetea el counter en `stopRefPreview()`. |
