# _deprecated/

Carpeta residual para archivos deprecados que se removieron del árbol activo
del frontend. **Esta carpeta está listada en `.gitignore`** — solo el README
está commiteado; el resto es ignorado por git.

## Estado actual (2026-09-24)

| Subcarpeta | Estado | Razón |
|---|---|---|
| `css-archive-monolith/` | ❌ **eliminado** | Era el monolito CSS original (368 KB, 28 archivos) — reemplazado por `css/base/`, `css/components/`, `css/skin/`, `css/widgets/`. Sin referencias. |
| `css-components/dashboard.css` | ❌ **eliminado** | Archivo trampa de 8 líneas (solo `.meters-toggle`). En commit D, `.meters-toggle` se consolidó en `meters.css` y este archivo se movió acá. Sin referencias. |

## Convención

- Los archivos se mueven **con su ruta relativa original** para preservar el
  contexto histórico (ej. `css/components/dashboard.css` →
  `_deprecated/css-components/dashboard.css`).
- Cada archivo movido mantiene su contenido intacto, sin ediciones.
- Si necesitás revisar el histórico de un archivo, restaurá temporalmente
  desde acá; si lo querés volver al árbol activo, mové de vuelta y commiteá.

## Por qué existe

Para evitar perder trazabilidad cuando se quita código del path activo.
Mantener archivos deprecados accesibles sin que contaminen el árbol activo
del frontend (que ya está limpio).
