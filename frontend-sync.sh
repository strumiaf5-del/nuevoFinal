#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# frontend-sync.sh — sincroniza /root/nuevoFinal/frontend/ → /var/www/masteringstudio/
# ════════════════════════════════════════════════════════════
#
# USO:
#   ./frontend-sync.sh                # rsync incremental
#   ./frontend-sync.sh --delete        # borra archivos en destino que
#                                       # no existen en origen (útil para
#                                       # renames/eliminaciones de CSS)
#   ./frontend-sync.sh --dry-run      # preview sin copiar
#   ./frontend-sync.sh --watch       # loop continuo cada 2s (dev)
#
# Qué sincroniza:
#   - index.html, login.html, favicon.svg
#   - css/  (toda la CSS activa — excluye _archive/ y _deprecated/)
#   - js/   (todos los scripts, incluido pro-features/)
#
# Qué NO sincroniza (por seguridad):
#   - .venv/, node_modules/, .git/
#   - archivos > 50MB (logs, fixtures grandes)
#
# INSTALACIÓN:
#   sudo cp frontend-sync.sh /usr/local/bin/frontend-sync
#   sudo chmod +x /usr/local/bin/frontend-sync
#
# Para correr en cada deploy:
#   ./frontend-sync.sh --delete
# ════════════════════════════════════════════════════════════

set -euo pipefail

SRC="${SRC:-/root/nuevoFinal/frontend/dist}"
DST="${DST:-/var/www/masteringaudio}"
LOG="${LOG:-/var/log/frontend-sync.log}"

# Defaults
DELETE=0
DRY_RUN=0
WATCH=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --delete)   DELETE=1; shift ;;
        --dry-run)  DRY_RUN=1; shift ;;
        --watch)    WATCH=1; shift ;;
        --src)      SRC="$2"; shift 2 ;;
        --dst)      DST="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,33p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown flag: $1" >&2
            exit 2
            ;;
    esac
done

# ── Validaciones ──
[[ -d "$SRC" ]] || { echo "ERROR: SRC no existe: $SRC" >&2; exit 1; }
[[ -f "$SRC/index.html" ]] || { echo "ERROR: SRC no parece un frontend (no hay index.html)" >&2; exit 1; }

# ── SRI guard: regenerar hashes antes de cada deploy ──
# Si un .js/.css cambió sin regenerar el integrity= del HTML, el browser
# bloquea el recurso (SRI mismatch) y la app rompe en cascada. El script
# reescribe los hashes stale in-place antes del rsync para que eso nunca
# llegue a producción. Ver frontend/tools/regen-sri.py.
if [[ -f "$SRC/tools/regen-sri.py" ]] && command -v python3 >/dev/null 2>&1; then
    if ! python3 "$SRC/tools/regen-sri.py" 2>&1 | tee -a "$LOG"; then
        echo "ERROR: regen-sri.py falló (¿archivos referenciados inexistentes?)" >&2
        exit 1
    fi
fi

mkdir -p "$DST"

# ── Build rsync args ──
RSYNC_ARGS=(
    --recursive
    --links
    --times                      # preservar mtime (para cache headers)
    --compress
    --human-readable
    --itemize-changes            # ver qué cambió
    --max-size=50m                # excluir archivos > 50MB
    --exclude='.git'
    --exclude='.venv'
    --exclude='node_modules'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='*.map'
    --exclude='.DS_Store'
    --exclude='Thumbs.db'
    --exclude='1.txt'            # placeholder local, no es parte del deploy
    --exclude='_archive/**'       # CSS legacy — fuera del repo
    --exclude='_deprecated'        # graveyard — gitignored, no va a producción
    --exclude='_deprecated/**'
    --exclude='tmp/**'
    --exclude='*.log'
    --exclude='.cache/**'
    --exclude='tools/'             # scripts dev — no va al docroot
    --exclude='audit/'             # informes internos — no publicar en docroot
)

if [[ $DELETE -eq 1 ]]; then
    RSYNC_ARGS+=(--delete --delete-after)
fi

if [[ $DRY_RUN -eq 1 ]]; then
    RSYNC_ARGS+=(--dry-run)
fi

run_sync() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync: $SRC → $DST  (delete=$DELETE dry-run=$DRY_RUN)" | tee -a "$LOG"
    rsync "${RSYNC_ARGS[@]}" "$SRC/" "$DST/" 2>&1 | tee -a "$LOG"
    local status=${PIPESTATUS[0]}
    if [[ $status -eq 0 ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync OK" | tee -a "$LOG"
        # Reload Caddy si está corriendo (no-op si no hay servicio).
        if command -v systemctl >/dev/null && systemctl is-active --quiet caddy 2>/dev/null; then
            # Caddy recarga automáticamente cuando ve cambios en archivos
            # servidos; no hace falta reload explícito.
            :
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync FAILED (exit=$status)" | tee -a "$LOG" >&2
        return $status
    fi
}

if [[ $WATCH -eq 1 ]]; then
    echo "Watching $SRC every 2s. Ctrl+C to stop."
    while true; do
        run_sync || true
        sleep 2
    done
else
    run_sync
fi
