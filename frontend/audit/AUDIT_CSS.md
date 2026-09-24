# Informe de Auditoría Exhaustiva de CSS — LGMDM Master Console

**Fecha:** 2026-09-23  
**Alcance:** Todos los estilos CSS cargados en el frontend (`css/**/*.css`, `index.html`).  
**Estado:** Diagnóstico completo — Plan de Remediación Listo.

---

## 1. Resumen Ejecutivo y Métricas Globales

Se realizó un escaneo automatizado y exhaustivo de los 27 archivos CSS vinculados en `index.html`, analizando sintaxis, propiedades inválidas, variables no resueltas, duplicados, colisiones de especificidad/cascada, escala de `z-index`, problemas de contraste y código muerto.

### Métricas de Diagnóstico:
| Métrica | Resultado | Estado |
| :--- | :--- | :--- |
| **Archivos CSS activos en `index.html`** | 27 archivos | Analizados |
| **Bloques de reglas analizados** | 1,482 bloques | Sin errores de llaves/balance |
| **Hojas huérfanas / obsoletas** | 1 (`css/components/studio.css`) | Requiere retiro |
| **Propiedades CSS sintácticamente inválidas** | 1 (`aria-busy: "true";` en CSS) | ❌ Error crítico |
| **Bugs de contraste severo / texto invisible** | 2 (`.btn-download`, `.btn-automaster`) | ❌ Bug visual |
| **Reglas duplicadas con colisión destructiva** | 1 (`.empty-state` en `utilities.css`) | ⚠️ Inconsistencia |
| **Colisiones de cascada entre hojas** | 1 (`.checkbox-row` en `utilities` vs `lgmdm`) | ⚠️ Usabilidad |
| **Violaciones de escala Z-Index canónica** | 3 (`14000`, `9999`, etc.) | ⚠️ Fragilidad visual |
| **Reglas vacías / linter warnings** | 1 (`.chain-family-visible`) | ℹ️ Limpieza |
| **Resiliencia de fallbacks de fuentes** | 2 variables (`--sans`, `--mono`) | ℹ️ Mejora de robustez |

---

## 2. Hallazgos Detallados por Categoría

### 2.1. Propiedad Inválida (Error de Parseo de Motor CSS)
- **Archivo:** [`css/components/utilities.css`](file:///root/rescate/css/components/utilities.css#L158)
- **Regla:** `.skeleton-loader` (Línea 158)
- **Código detectado:**
  ```css
  .skeleton-loader {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: var(--space-4);
    aria-busy: "true"; /* ❌ Error: aria-busy es un atributo HTML, no una propiedad CSS */
  }
  ```
- **Impacto:** Los motores de renderizado (Blink/Gecko/WebKit) descartan la declaración como `Unknown property`.
- **Remediación:** Eliminar `aria-busy: "true";` del bloque CSS. La accesibilidad ARIA se gestiona directamente en el marcado HTML mediante el atributo `aria-busy="true"`.

---

### 2.2. Bugs de Contraste Severo y Accesibilidad (WCAG AA/AAA)
- **Archivo:** [`css/components/buttons.css`](file:///root/rescate/css/components/buttons.css#L88-L95)
- **Regla:** `.btn-download` (Líneas 88–95)
- **Código detectado:**
  ```css
  .btn-download {
    background: color-mix(in srgb, var(--ui-warm-soft) 14%, transparent);
    border: 1px solid var(--ui-warn);
    color: var(--ui-surface); /* ❌ Bug: fondo oscuro translúcido con texto color superficie oscura (#141414) */
    margin-top: var(--space-2);
    display: none;
    font-weight: 700;
  }
  ```
- **Impacto:** El texto "Descargar Master" resulta completamente invisible o ilegible sobre el fondo oscuro en temas oscuros (contraste menor a 1.2:1, fallando WCAG).
- **Remediación:** Cambiar a `color: var(--ui-warn);` (idéntico a `.btn-ab` y `.btn-report`), garantizando contraste ámbar vibrante legible.

- **Archivo:** [`css/components/buttons.css`](file:///root/rescate/css/components/buttons.css#L109-L116)
- **Regla:** `.btn-automaster` (Líneas 109–116)
- **Código detectado:**
  ```css
  .btn-automaster {
    background: linear-gradient(135deg, var(--ui-warn-2) 0%, var(--ui-warn) 50%, ...);
    color: var(--ui-surface);
  }
  ```
- **Remediación:** Estandarizar `color: var(--ui-bg, #0a0907);` para asegurar contraste tipográfico nítido y consistente sobre el gradiente dorado/ámbar en cualquier tema.

---

### 2.3. Duplicación Interna Destructiva en el Mismo Archivo
- **Archivo:** [`css/components/utilities.css`](file:///root/rescate/css/components/utilities.css)
- **Regla:** `.empty-state`
  - Declaración 1 (L183–195):
    ```css
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0.75rem;
      padding: var(--space-8) var(--space-4);
      text-align: center;
      color: var(--ui-muted);
      border: 1px dashed var(--ui-border);
      border-radius: var(--radius);
      background: var(--ui-panel);
    }
    ```
  - Declaración 2 (L697–711):
    ```css
    .empty-state {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: var(--ui-muted);
      text-align: center;
      gap: var(--space-2);
      background: rgba(255, 255, 255, 0.01);
      border: 1px dashed var(--ui-border-2);
      border-radius: var(--radius);
      padding: var(--space-4);
      min-height: 180px;
    }
    ```
- **Impacto:** La declaración 2 sobreescribe de forma impredecible padding (`var(--space-4)` vs `var(--space-8)`), gap y fondo, dejando la declaración 1 como código zombi en el mismo archivo.
- **Remediación:** Consolidar en una única definición canónica de `.empty-state` con `min-height: 180px; flex: 1; gap: var(--space-3); padding: var(--space-6) var(--space-4); border: 1px dashed var(--ui-border-2); background: var(--ui-panel, rgba(255,255,255,0.01));`.

---

### 2.4. Colisión de Cascada entre Archivos (`.checkbox-row`)
- **Archivos:**
  - Base: [`css/components/utilities.css#L596`](file:///root/rescate/css/components/utilities.css#L596)
  - Sobreescritura tardía: [`css/components/lgmdm.css#L37`](file:///root/rescate/css/components/lgmdm.css#L37)
- **Problema:** En `utilities.css`, `.checkbox-row` define `align-items: center; cursor: pointer;`. Luego, `lgmdm.css` (cargado mucho después) aplica `align-items: flex-start; gap: 6px;` y no define cursor, desalineando verticalmente el checkbox con respecto a su etiqueta y perdiendo la indicación de clicabilidad.
- **Remediación:** Normalizar `.checkbox-row` en `lgmdm.css` para respetar `align-items: center; cursor: pointer;`.

---

### 2.5. Estandarización de la Escala Canónica de Z-Index
En [`css/base/tokens.css`](file:///root/rescate/css/base/tokens.css) existe una escala semántica documentada:
```css
--z-base:        0;
--z-aurora:      90;
--z-handle:      400;
--z-insert-rack: 1000;
--z-toast:       1100;
--z-modal:       1200;
--z-admin:       1300;
--z-switcher:    1400;
--z-compat:      2147483647;
```
Se detectaron valores numéricos arbitrarios ("magic numbers") que rompen el apilamiento:
1. [`css/widgets/pro-insert-rack.css#L272`](file:///root/rescate/css/widgets/pro-insert-rack.css#L272):
   `.pir-detail-overlay { z-index: 14000; }` ➔ Supera al selector de temas y al admin. Debe ser `z-index: var(--z-modal, 1200);`.
2. [`css/components/lgmdm-studio.css#L688`](file:///root/rescate/css/components/lgmdm-studio.css#L688):
   `.toast-container { z-index: 9999; }` ➔ Debe ser `z-index: var(--z-toast, 1100);`.
3. [`css/components/base.css#L173`](file:///root/rescate/css/components/base.css#L173):
   `.sr-only-focusable:focus { z-index: 9999; }` ➔ Debe ser `z-index: var(--z-modal, 1200);`.

---

### 2.6. Archivo Huérfano y Retiro de Carga Bloqueante
- **Archivo:** [`css/components/studio.css`](file:///root/rescate/css/components/studio.css) (401 líneas)
- **Vínculo en HTML:** [`index.html#L25`](file:///root/rescate/index.html#L25) (`<link href="css/components/studio.css" rel="stylesheet"/>`)
- **Diagnóstico:** Contiene 48 clases obsoletas de un prototipo temprano (`.lg-studio-shell`, `.studio-heading`, `.studio-meter`, etc.). Ninguna existe en `index.html` ni en los 61 archivos JavaScript. La única clase compartida (`.lg-chain-control-strip`) ya está implementada de forma más completa y canónica en [`css/components/lgmdm.css`](file:///root/rescate/css/components/lgmdm.css#L73).
- **Impacto:** 8 KB de payload CSS síncrono innecesario en la ruta crítica de renderizado (`<head>`).
- **Remediación:** Remover el enlace `<link href="css/components/studio.css" rel="stylesheet"/>` de `index.html`.

---

### 2.7. Limpieza de Reglas Vacías y Resiliencia Tipográfica
1. **Regla vacía:** [`css/widgets/chain-family-tabs.css#L54`](file:///root/rescate/css/widgets/chain-family-tabs.css#L54)
   `.chain-family-visible { /* comment only */ }` ➔ Se elimina o se le asigna propiedad concreta para silenciar advertencias de analizadores CSS.
2. **Fallbacks de tipografía:** En [`css/base/tokens.css#L17`](file:///root/rescate/css/base/tokens.css#L17), agregar fallbacks de fuentes de sistema:
   ```css
   --sans: var(--ui-font-display, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif);
   --mono: var(--ui-font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
   ```

---

## 3. Matriz de Remediación

| # | Archivo | Líneas | Acción |
|---|---|---|---|
| 1 | `css/components/utilities.css` | 158 | Eliminar `aria-busy: "true";` de `.skeleton-loader`. |
| 2 | `css/components/buttons.css` | 91, 111 | Corregir contraste: `.btn-download` (`--ui-warn`) y `.btn-automaster` (`--ui-bg`). |
| 3 | `css/components/utilities.css` | 183–209, 697–720 | Consolidar definición de `.empty-state` eliminando duplicado. |
| 4 | `css/components/lgmdm.css` | 37–41 | Alinear `.checkbox-row` con `align-items: center; cursor: pointer;`. |
| 5 | `css/widgets/pro-insert-rack.css` | 272 | Reemplazar `z-index: 14000;` por `var(--z-modal, 1200);`. |
| 6 | `css/components/lgmdm-studio.css` | 688 | Reemplazar `z-index: 9999;` por `var(--z-toast, 1100);`. |
| 7 | `css/base/tokens.css` | 17–18 | Añadir fallbacks nativos del sistema a `--sans` y `--mono`. |
| 8 | `css/widgets/chain-family-tabs.css` | 54–58 | Limpiar bloque vacío `.chain-family-visible`. |
| 9 | `index.html` | 25 | Remover `<link href="css/components/studio.css" rel="stylesheet"/>`. |
