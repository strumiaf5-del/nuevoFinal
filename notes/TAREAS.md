# TAREAS — LGMDM Frontend

> Apunte de tareas compartidas entre Mimo y el usuario.
> Última actualización: 2026-09-24 (audit completo de /root/aporte)

---

## 🔍 AUDIT — `/root/aporte` vs `/root/nuevoFinal/frontend/`

**Objetivo del audit:** decidir qué tomar de aporte, qué dejar, en qué orden, y qué beneficio concreto trae cada integración.

### Comparativa general

| Métrica | `/root/aporte` | nuestro repo |
|---|---|---|
| Total archivos | 123 | 156 |
| CSS activos | 28 | 28 |
| JS activos | 61 | 67 |
| Tamaño total | 1.9 MB | 2.4 MB |
| index.html (líneas) | 1978 | 2039 |
| login.html (líneas) | 539 | 76 |
| login-inline.css | ❌ no tiene | ✅ 233 líneas |
| login-inline.js | ❌ no tiene | ✅ existe |
| `_deprecated/` masiva | ❌ no | ✅ 384 KB |
| `pro-features/helpers` extraídos | ❌ no | ✅ 3 archivos |
| `10-meters-dashboard.js` (líneas) | **875** | **406** |
| `themes-professional-skin.css` (bytes) | **84101** | **34416** |
| `34-premium-suite.js` (líneas) | 3504 | 3159 |
| `17-keyboard-shortcuts.js` activo | ✅ sí | ❌ archivado |

### Veredicto del audit

**Aporte = versión más simple y limpia, con menos features propias.** Nuestro repo = versión más rica (más funciones), pero con **regresiones críticas** en meters y skin incompleto.

---

## 🟥 FASE 1 — CRÍTICO (regresiones a corregir)

### 1.1 — Restaurar `10-meters-dashboard.js` (live meters)

**Problema concreto:** tu `10-meters-dashboard.js` perdió 470 líneas de código. Esto rompe los meters en vivo (Peak/RMS/LUFS/TruePeak/Stereo no se actualizan con el audio).

**Funciones que faltan en tu repo** (presentes en aporte):

| Función | Qué hace |
|---|---|
| `getSliderNum` | Lee valor numérico de un slider |
| `isChecked` | Lee estado de un checkbox |
| `isAudioPlaying` | Detecta si hay audio activo |
| `readTimeDomain` | Lee `getFloatTimeDomainData` del AnalyserNode |
| `readFrequency` | Lee `getByteFrequencyData` del AnalyserNode |
| `getBandDb` | Calcula dB integrado por banda (low/mid/high) |
| `tickLiveMeters` | Loop RAF que actualiza meters continuamente |
| `setupLiveMeters` | Inicializa el sistema de meters |
| `stopLiveMeters` | Detiene el loop |
| `onMediaPlay` | Hook al evento `play` del `<audio>` |
| `onMediaPause` | Hook al evento `pause` del `<audio>` |

**Estrategia: MERGE quirúrgico**, NO copy-paste completo.

**Acción concreta:**
1. Copiar las 11 funciones faltantes desde aporte (con sus helpers privados como `getSliderNum`/`isChecked`)
2. **MANTENER** las 5 funciones que ya tenemos: `startDashboardPolling`, `stopDashboard`, `startDashboard`, `teardownLiveMeters`, `updateMetersSummary`
3. **MANTENER** las adiciones recientes: `vuPreLufs`, `vuPostGr` (Pre-LUFS y Post-GR que agregaste)
4. Integrar `setupLiveMeters` + `tickLiveMeters` dentro del flujo existente de `startDashboardPolling` (probablemente `setupLiveMeters` se llama dentro de `startDashboardPolling`)

**Beneficio:**
- ✅ Los meters se actualizan en tiempo real mientras hay audio
- ✅ Las barras de GR (Gain Reduction) muestran valores reales del backend
- ✅ Las bandas (low/mid/high) responden correctamente
- ✅ El sistema pause/play funciona

**Riesgo:** BAJO — son funciones puras, no rompen UI.

---

### 1.2 — Diagnóstico de orden de carga (`34-premium-suite.js` + helpers)

**Problema potencial:** nuestro repo extrajo helpers a `pro-features/premium-utils.js`, `pro-features/visualizer-render.js`, `pro-features/wav-encoder.js`. En aporte, todo está inline en `34-premium-suite.js`.

**Estado actual** (verificado en `index.html`):
```
línea 1942: js/pro-features/wav-encoder.js
línea 1944: js/pro-features/premium-utils.js
línea 1946: js/pro-features/visualizer-render.js
línea 1948: js/34-premium-suite.js  ← Carga DESPUÉS de los helpers ✓
```

✅ **El orden está BIEN.** Los 3 helpers cargan ANTES de 34. No hay problema de carga.

**Acción:** AUDIT SIN CAMBIOS — solo confirmar que el patrón actual es correcto. Documentado en este archivo como "verificado OK".

---

## 🟧 FASE 2 — IMPORTANTE (visual / fidelidad)

### 2.1 — Completar `themes-professional-skin.css`

**Problema concreto:** tu skin tiene 34 KB, el de aporte tiene 84 KB. Te faltan ~50 KB de estilos visuales (glass morphism completo, glow effects, animaciones, focus rings).

**Secciones del skin en aporte** (que en tu repo están más delgadas o ausentes):

| Sección en aporte | Sección en tu repo | Status |
|---|---|---|
| MASTER BUS CONSOLE RACK CHASSIS | (distribuido en lg-console) | ⚠️ posible gap |
| SIGNAL SCOPE (WAVEFORM) | (en lg-wave-panel) | ⚠️ posible gap |
| METER BRIDGE (DUAL CHANNEL STEREO VU) | Meter Rack | ⚠️ nombre diferente |
| SPECTRUM ANALYZER (FFT 20Hz-20kHz) | Spectrum + Waterfall Panels | ⚠️ nombre diferente |
| MASTER TRANSPORT CONTROLLER | Transport Controls | ✅ tenés |
| AUXILIARY METERS DASHBOARD WRAP | (no existe en tu repo) | 🔴 falta |

**Estrategia: DIFF selectivo**, NO copy-paste.

**Acción concreta:**
1. Diffear `themes-professional-skin.css` de aporte vs nuestro
2. Identificar bloques de CSS específicos que falten
3. Copiar **solo** los bloques que NO rompan tu layout actual
4. **NO** traer "AUXILIARY METERS DASHBOARD WRAP" si no lo necesitamos (es huérfano en aporte)

**Beneficio:**
- ✅ Visual más rico: glow en headers, glass morphism completo
- ✅ Animaciones pulse en badges
- ✅ Scrollbar custom
- ✅ Focus rings consistentes

**Riesgo:** MEDIO — pueden romperse selectores. Hacer commit chico + verificar visual.

---

### 2.2 — `17-keyboard-shortcuts.js` (modal de atajos `?`)

**Estado actual:**
- Aporte: activo en `/js/`
- Tu repo: en `_archive/` (no se carga)

**Decisión recomendada:** **NO tomar de aporte.** El modal de atajos fue archivado intencionalmente. Restaurarlo requiere verificar que las shortcuts no choquen con las nuevas features (Aurora oculta, EQ chain, autosave, etc.).

**Beneficio de restaurarlo:** modal `?` muestra lista completa de shortcuts.
**Beneficio de dejarlo archivado:** evita conflictos con atajos nuevos.

**Acción:** dejar como está por ahora. Solo reconsiderar si el usuario explícitamente pide restaurar.

---

## 🟨 FASE 3 — OPCIONAL (mejoras nice-to-have)

### 3.1 — Eliminar `_deprecated/css-archive-monolith/` (368 KB)

**Problema:** tu repo tiene 24 archivos CSS viejos en `_deprecated/css-archive-monolith/` que ocupan espacio sin usarse.

**Beneficio:** ~368 KB menos en el repo. `git status` más limpio.

**Riesgo:** BAJO si verificamos que ningún archivo vivo importa de ahí.

**Acción:**
1. `grep -r "css-archive-monolith" frontend/` para confirmar 0 referencias
2. `git rm -r frontend/_deprecated/css-archive-monolith/`
3. Commit chico separado

---

### 3.2 — Eliminar `_deprecated/css-components/dashboard.css` y consolidar `.meters-toggle`

**Estado actual:**
- Tu repo tiene `_deprecated/css-components/dashboard.css` (8 líneas, solo `.meters-toggle`)
- En commit D, moviste `.meters-toggle` a `meters.css`
- Pero el archivo huérfano sigue en `_deprecated`

**Acción:**
1. Verificar que `_deprecated/css-components/dashboard.css` no se carga desde `index.html`
2. Si no se carga → `git rm` + commit chico

---

## 🟩 Lo que NO tomar de aporte (decline list)

| Archivo / patrón | Por qué NO |
|---|---|
| `css/_archive/console-shell.css` (aporte) | Ya tenemos layout más moderno |
| `css/_legacy_archive/*` (aporte) | Código muerto por definición |
| `js/_legacy_archive/*` (aporte, 252 KB) | Código muerto |
| `css/components/dashboard.css` (aporte) | Lo borramos en commit D con razón |
| Reorganización masiva de CSS por carpetas | Migración costosa, beneficio incierto |
| Consolidar `pro-features/helpers` de vuelta en 34 | Romperíamos la separación actual, y los helpers cargan OK antes del 34 |

---

## 📋 Plan de ejecución (orden recomendado)

### Orden 1 — URGENTE: `10-meters-dashboard.js`
- Commit único: `fix(frontend): restaurar live meters — merge de 11 funciones de /root/aporte`
- Tiempo estimado: 30 min
- Riesgo: bajo
- Verificación: ver meters moviéndose en console con audio reproduciéndose

### Orden 2 — Skin selectivo
- Pre-requisito: diff completo de skin
- Commit único: `feat(skin): merge selectivo de /root/aporte skin — secciones que faltan`
- Tiempo estimado: 1-2 horas
- Riesgo: medio (verificación visual)
- Verificación: hard refresh + screenshots antes/después

### Orden 3 (opcional) — Limpieza de `_deprecated/`
- 2 commits chicos separados
- Tiempo: 15 min total
- Riesgo: bajo

---

## 📌 Estado actual del repo (antes de este audit)

### ✅ Pendientes
- (todas las tareas del audit completadas 🎉)

### ⏳ En curso
- (nada)

### ⏳ En curso
- (nada)

### ✅ Completadas (sesión previa)

- ✅ Consola workspace unificada (preview 16:9, spectrum+waterfall 200px compartido)
- ✅ EQ Chain Response canvas (10 biquads en cascada — RBJ Audio EQ Cookbook)
- ✅ Aurora movido de `#console-workspace` → body level
- ✅ Aurora ocultado con `display: none !important`
- ✅ App footer fixed dentro de `#console-workspace` (28px, oculto en otros workspaces)
- ✅ Workspace llena el viewport (`flex: 1 1 auto` en cadena flex)
- ✅ `lg-console` crece con `flex: 1 1 auto` (continuidad visual hasta footer)
- ✅ mb-vu-section: 2 rows nuevos (Pre-LUFS, Post-GR)

### ✅ Completadas (audit /root/aporte)

- ❌ **Fase 1.1**: **REVERTIDO** — el preview ya funcionaba con métricas en vivo por polling. Agregar 470 líneas de Web Audio API (commit `661a46a`) rompió el preview (500 en `/api/preview/source`). Revertido en commit `0364c8f`. Lección: **validar antes de "arreglar"**.
- ✅ **Fase 2.1**: Skin selectivo — merge de 5 secciones de aporte (Rack, Signal Scope, Meter Bridge, Spectrum, Transport). Commit `9dfca0a`. Skin creció 34 KB → 45 KB.
- ✅ **Fase 3.1**: Eliminar `_deprecated/css-archive-monolith/` (368 KB) — carpeta estaba gitignored, eliminado local. Commit `b6c8832` (solo el README actualizado).
- ✅ **Fase 3.2**: Eliminar `_deprecated/css-components/dashboard.css` — junto con 3.1 en commit `b6c8832`.

### ✅ Verificadas (audit)

- ✅ **Orden de carga** (`34-premium-suite.js` + helpers): correcto, los 3 helpers cargan ANTES del 34. Sin cambios necesarios.

---

## 🔧 Convenciones

- Frase secreta para ejecutar cambios: **"OK MIMO"**
- Sin la frase: solo conversación / propuestas — cero código modificado
- Este archivo `notes/TAREAS.md` se puede modificar SIN frase secreta (es documentación, no código)
- El usuario puede revisar `git status` y `git log` en cualquier momento

---

## 📝 Notas del audit

- Aporte tiene `js/pro-features/` con 14 widgets (mismos que nosotros) pero SIN los 3 helpers extraídos (`premium-utils`, `visualizer-render`, `wav-encoder`). Esto confirma que en algún momento alguien consolidó los helpers en 34 y luego los volvieron a separar.
- El usuario explícitamente dijo "no necesito la frase secreta para escribir solo este archivo" — esta nota documenta esa excepción.
- La sesión previa gastó mucho esfuerzo en sync, layout fix, footer, etc. Este audit es una oportunidad para evitar futuros retrocesos.
