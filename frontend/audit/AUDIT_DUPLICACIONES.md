# Auditoría Exhaustiva de Duplicaciones: Funciones, Reglas CSS e IDs

> **Proyecto:** LGMDM · Intelligent Mastering Console  
> **Área:** Frontend (`index.html`, `css/`, `js/`, `js/pro-features/`)  
> **Tipo:** Detección de código redundante, colisiones de IDs y duplicación de reglas  

---

## 1. Resumen de Hallazgos de Duplicación

Se ejecutaron escáneres estáticos automatizados sobre todo el árbol de código del frontend (61 scripts JavaScript activos y 27 hojas de estilo CSS).

### Métricas Globales de Duplicación

| Categoría | Total Analizado | Duplicaciones Detectadas | Nivel de Impacto |
| :--- | :---: | :---: | :--- |
| **Funciones & Helpers JS** | ~450 funciones | **28 funciones / utilidades** con nombres o código duplicado entre archivos | 🟡 Medio (Mantenibilidad & DRY) |
| **Redeclaraciones Internas** | 61 archivos | **1 archivo crítico** ([`reference-library-picker.js`](file:///root/rescate/js/reference-library-picker.js)) redeclara `bindOnce` 4 veces | 🟢 Leve (Código redundante interno) |
| **Objetos de Estilo / Paleta** | 6 widgets | **6 archivos** duplican el objeto `PALETTE` consultando `getComputedStyle` | 🟡 Medio (Rendimiento innecesario) |
| **Selectores CSS Duplicados** | 1.360 selectores | **124 selectores** declarados en múltiples hojas de estilo | 🟡 Medio (Sobrescritura & Especificidad) |
| **Bloques de Reglas CSS Idénticos** | ~1.800 bloques | **39 bloques de estilos idénticos** (≥ 3 propiedades CSS repetidas) | 🟢 Leve (Oportunidad de optimización) |
| **IDs en HTML Estático** | 568 IDs | **0 IDs duplicados** en [`index.html`](file:///root/rescate/index.html) | 🟢 Óptimo (100% únicos) |
| **Solapamiento ID Estático ↔ Dinámico** | 285 IDs dinámicos | **11 IDs** creados en JS que también existen en HTML | 🟢 Controlado (Protegidos con guardas `if (!el)`) |

---

## 2. Detalle de Duplicaciones en JavaScript

### A. Redeclaración de `const bindOnce` 4 veces en el mismo archivo
* **Ubicación:** [`js/reference-library-picker.js`](file:///root/rescate/js/reference-library-picker.js#L104)
* **Líneas:** 104, 171, 214 y 240.
* **Problema:** En lugar de declarar `const bindOnce` una única vez en el scope del módulo IIFE, se re-declara dentro de `_renderList()`, `_buildModal()`, `_injectButton()` e `init()`.
* **Solución Propuesta:** Mover `const bindOnce = LGMDM.ui?.bindOnce || ...` al encabezado del módulo (línea 10) y eliminar las 4 redeclaraciones internas.

---

### B. Objeto `PALETTE` duplicado en 6 widgets de `js/pro-features/`
* **Ubicación:** 
  1. [`js/pro-features/loudness-penalty-widget.js#L11`](file:///root/rescate/js/pro-features/loudness-penalty-widget.js#L11)
  2. [`js/pro-features/ms-imager-widget.js#L11`](file:///root/rescate/js/pro-features/ms-imager-widget.js#L11)
  3. [`js/pro-features/phase-rotation-widget.js#L11`](file:///root/rescate/js/pro-features/phase-rotation-widget.js#L11)
  4. [`js/pro-features/reference-match-widget.js#L11`](file:///root/rescate/js/pro-features/reference-match-widget.js#L11)
  5. [`js/pro-features/saturation-widget.js#L11`](file:///root/rescate/js/pro-features/saturation-widget.js#L11)
  6. [`js/pro-features/spectral-tilt-widget.js#L11`](file:///root/rescate/js/pro-features/spectral-tilt-widget.js#L11)
* **Código Duplicado en los 6 archivos:**
  ```javascript
  const PALETTE = (() => {
    if (typeof document === 'undefined') return null;
    const s = getComputedStyle(document.documentElement);
    return {
      good: s.getPropertyValue('--ui-good').trim() || '#45f6b2',
      warn: s.getPropertyValue('--ui-warn').trim() || '#ffbd4a',
      danger: s.getPropertyValue('--ui-danger').trim() || '#ff4264',
      accent: s.getPropertyValue('--ui-accent').trim() || '#23e7ff',
      text: s.getPropertyValue('--ui-text').trim() || '#f4f7ff',
      muted: s.getPropertyValue('--ui-muted').trim() || '#8995b0',
      bg: s.getPropertyValue('--ui-surface').trim() || '#0d1220'
    };
  })();
  ```
* **Problema:** En [`js/01-state.js#L81`](file:///root/rescate/js/01-state.js#L81) ya existe la función `window.LGMDM.themeColors()` con caché centralizada y refresco automático al cambiar el tema visual. Los 6 widgets ignoran la función existente y ejecutan llamadas pesadas a `getComputedStyle(...)` en su carga.
* **Solución Propuesta:** Reemplazar el bloque IIFE duplicado por:
  ```javascript
  const PALETTE = (window.LGMDM?.themeColors && window.LGMDM.themeColors()) || { ...fallback };
  ```

---

### C. Funciones de Estado Duplicadas (`getSelectedFile`, `getLastAnalysis`)
* **Ubicación:** Duplicadas en 4 archivos:
  - [`js/01-state.js`](file:///root/rescate/js/01-state.js#L219) (Fuente autoritativa)
  - [`js/20-pro-upgrades.js`](file:///root/rescate/js/20-pro-upgrades.js#L7)
  - [`js/29-analysis-view.js`](file:///root/rescate/js/29-analysis-view.js#L95)
  - [`js/34-premium-suite.js`](file:///root/rescate/js/34-premium-suite.js#L14)
* **Detalle:** Cada uno implementa su propio getter local leyendo `LGMDM.state.selectedFile` o `LGMDM.state.lastAnalysisData`.
* **Solución Propuesta:** Consumir directamente los métodos autoritativos de `LGMDM.state.getSelectedFile()` y `LGMDM.state.getLastAnalysis()`.

---

### D. Algoritmos Matemáticos de Gráficos de Frecuencia Duplicados
* **Ubicación:**
  - [`js/pro-features/reference-match-widget.js#L40`](file:///root/rescate/js/pro-features/reference-match-widget.js#L40)
  - [`js/pro-features/saturation-widget.js#L42`](file:///root/rescate/js/pro-features/saturation-widget.js#L42)
  - [`js/pro-features/spectral-tilt-widget.js#L41`](file:///root/rescate/js/pro-features/spectral-tilt-widget.js#L41)
* **Código Duplicado:**
  ```javascript
  function _xFreq(freq, width) { return (Math.log10(Math.max(20, freq) / 20) / Math.log10(1000)) * width; }
  function _yDb(db, height, minDb, maxDb) { return height - ((db - minDb) / (maxDb - minDb)) * height; }
  function _freqFromX(x, width) { return 20 * Math.pow(1000, x / width); }
  ```
* **Solución Propuesta:** Mover estos helpers de coordenadas logarítmicas a la clase base [`36-base-canvas-widget.js`](file:///root/rescate/js/36-base-canvas-widget.js) como métodos estáticos o heredados: `BaseCanvasWidget.freqToX(freq, width)` y `BaseCanvasWidget.dbToY(db, height, minDb, maxDb)`.

---

### E. Dependencia Invertida de Stubs de Tabs (`40`, `41`, `42`, `43`)
* **Ubicación:** [`js/40-tab-compliance.js`](file:///root/rescate/js/40-tab-compliance.js), [`js/41-tab-abx.js`](file:///root/rescate/js/41-tab-abx.js), [`js/42-tab-codec.js`](file:///root/rescate/js/42-tab-codec.js), [`js/43-tab-waterfall.js`](file:///root/rescate/js/43-tab-waterfall.js).
* **Detalle:** Estos 4 archivos son simples stubs (cascarones) que llaman a `global._lgmdmRenderComplianceTab`, `global._lgmdmRenderAbxTab`, etc., cuya lógica real reside en [`js/34-premium-suite.js`](file:///root/rescate/js/34-premium-suite.js).
* **Solución Propuesta:** En [`index.html`](file:///root/rescate/index.html), mover `js/34-premium-suite.js` para que se cargue **antes** de los archivos `40-43`, o consolidar los stubs directamente en la suite premium.

---

## 3. Detalle de Duplicaciones en CSS

### A. Clases Utilitarias con Nombres Distintos y Reglas Idénticas
En [`css/components/studio-pro.css`](file:///root/rescate/css/components/studio-pro.css), se detectaron pares de clases con definiciones 100% idénticas:

| Clase 1 | Clase 2 | Regla CSS Idéntica Compartida |
| :--- | :--- | :--- |
| `.pro-flex-between` | `.pro-meter-row` | `display: flex; justify-content: space-between; align-items: center;` |
| `.pro-flex-between-mb` | `.pro-doctor-head` | `display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;` |
| `.pro-flex-center-14` | `.pro-flex-center-mb` | `display: flex; justify-content: center; gap: 14px; margin-bottom: 20px;` |
| `.pro-output-row` | `.pro-codec-output-row`| `display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin-top: 10px;` |

### B. Repetición de Bloques en Widgets Pro (`pro-widgets-v2.css`)
En [`css/widgets/pro-widgets-v2.css`](file:///root/rescate/css/widgets/pro-widgets-v2.css), las tres tarjetas `.reverb-widget`, `.dr-meter-widget` y `.lw-widget` repiten bloques idénticos:
```css
/* Repetido 3 veces en pro-widgets-v2.css */
.reverb-widget__head, .dr-meter-widget__head, .lw-widget__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.reverb-widget__sub-card, .dr-meter-widget__sub-card, .lw-widget__sub-card {
  background: var(--ui-panel);
  border: 1px solid var(--ui-border);
  border-radius: var(--radius);
  padding: 10px 12px;
}
```

### C. Sobrescrituras y Conflictos de Especificidad
- `.small-text`:
  - En [`css/components/utilities.css`](file:///root/rescate/css/components/utilities.css): `font-size: var(--text-sm); opacity: 0.85;`
  - En [`css/components/lgmdm.css`](file:///root/rescate/css/components/lgmdm.css): `font-size: var(--text-xs); color: var(--ui-muted); line-height: 1.45;`
  - Como `lgmdm.css` se carga al final, `var(--text-xs)` es el valor que se impone, dejando la regla de `utilities.css` como código muerto/anulado.
- `.checkbox-row`:
  - Redefinido en `utilities.css` y `lgmdm.css` con pequeñas variaciones de gap (4px vs 6px).

---

## 4. Detalle de IDs: Estáticos y Dinámicos

### Verificación de IDs Estáticos en `index.html`
- **Total de IDs en el documento:** 568
- **IDs duplicados:** **0** (Todos los elementos estáticos tienen un ID único y válido).

### Solapamiento con Elementos Creados Dinámicamente en JS
Se analizaron los 285 IDs generados mediante JavaScript en tiempo de ejecución. 11 de ellos coinciden con IDs que existen en el HTML inicial:

```mermaid
flowchart LR
    subgraph HTML ["index.html (HTML Inicial)"]
        H1["#toast-container"]
        H2["#historyToggleBtn"]
        H3["#btnOpenPremiumSuite"]
        H4["#btnOpenRefLib"]
        H5["#auth-user-bar"]
    end
    subgraph JS ["Módulos JavaScript"]
        J1["00-ui-core.js: ensureToastContainer()"] -->|Guardado: if (!c)| H1
        J2["18-undo-redo.js"] -->|Guardado: if (document.getElementById(...)) return| H2
        J3["34-premium-suite.js"] -->|Guardado: if (!btn) create...| H3
        J4["reference-library-picker.js"] -->|Guardado: if (btn) bind...| H4
        J5["00-auth.js: renderUserBar()"] -->|Limpia bar.innerHTML antes de recrear| H5
    end
```

**Diagnóstico:** Todos los solapamientos cuentan con comprobaciones defensivas (`if (!el)` o limpieza previa de contenedor `innerHTML = ''`), por lo que **no provocan colisiones de ID dobles en el DOM**.

---

## 5. Plan de Acción Propuesto (Deduplicación & Limpieza)

### Componente 1: Limpieza de JavaScript
1. **[`MODIFY`] `js/reference-library-picker.js`:**
   - Unificar las 4 declaraciones de `const bindOnce` a una única definición a nivel de módulo.
2. **[`MODIFY`] Widgets en `js/pro-features/`:**
   - Sustituir la IIFE `PALETTE` en los 6 widgets por el consumo centralizado de `window.LGMDM.themeColors()`.
3. **[`MODIFY`] `js/36-base-canvas-widget.js`:**
   - Incorporar los helpers de transformación logarítmica de frecuencia (`freqToX`, `dbToY`, `xToFreq`) en la clase base para que todos los widgets canvas los hereden sin duplicar matemáticas.
4. **[`MODIFY`] `index.html`:**
   - Ajustar el orden de carga para que `js/34-premium-suite.js` cargue antes de `js/40-tab-compliance.js` a `js/43-tab-waterfall.js`.

### Componente 2: Consolidación de CSS
1. **[`MODIFY`] `css/widgets/pro-widgets-v2.css`:**
   - Agrupar selectores compartidos (`.pro-widget-card__head`, `.pro-widget-card__sub-card`) reduciendo 45 líneas repetidas.
2. **[`MODIFY`] `css/components/studio-pro.css`:**
   - Consolidar las clases clonadas (`.pro-flex-between` / `.pro-meter-row`, etc.) unificando los selectores mediante comas.
3. **[`MODIFY`] `css/components/utilities.css`:**
   - Remover reglas muertas de `.small-text` y `.checkbox-row` que son sobrescritas obligatoriamente por `lgmdm.css`.

---

## 6. Plan de Verificación

### Pruebas Automatizadas
1. **Verificación Sintáctica:** Ejecutar `node --check` sobre todos los archivos `.js` modificados.
2. **Prueba de Regresión de IDs:** Ejecutar `scratch/find_dup_ids.py` para asegurar que sigan existiendo 0 IDs duplicados.
3. **Prueba de Consumo de Paleta:** Verificar que los 6 widgets de `pro-features` rendericen sus canvas correctamente con los colores del tema activo.

### Verificación Manual
1. **Cambio de Tema:** Cambiar de tema en la interfaz (botón 🎨 en el header) y verificar que los widgets Pro (Ms Imager, Phase Rotation, Saturation, etc.) actualicen sus colores dinámicamente sin requerir reload.
2. **Biblioteca de Referencias:** Abrir el modal de biblioteca de referencias (📚) y comprobar que el buscador, re-escaneo y selección funcionen tras unificar `bindOnce`.
3. **Tabs Pro:** Navegar por los tabs de Compliance, ABX, Codec y Waterfall en la Suite Pro y verificar que carguen sin mostrar errores de stub no inicializado.
