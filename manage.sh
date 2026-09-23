#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# manage.sh — Service manager interactivo para LGMDM
# USO:  sudo manage <service> <action> [opts]
#       sudo manage status              (resumen de todo)
#       sudo manage --help              (esta ayuda)
#
# El script vive en /root/nuevoFinal/manage.sh pero hay un symlink
# en /usr/local/bin/manage — funciona globalmente sin path.
#
# Servicios:
#   backend    FastAPI (uvicorn) en 127.0.0.1:8000
#   caddy      Web server (HTTPS + reverse proxy)
#   frontend   Static files en /var/www/masteringstudio/
#   duckdns    DuckDNS update timer (systemd)
#
# Acciones por servicio:
#   start      Iniciar
#   stop       Detener (pide confirmación salvo -y/--yes)
#   restart    stop + start (pide confirmación salvo -y/--yes)
#   status     Estado actual (PID, puerto, log reciente)
#   logs [N]   tail -F de las últimas N líneas (default 50, N=0 = follow)
#   sync       (solo frontend) rsync src → /var/www/masteringstudio/
#
# Ejemplos:
#   sudo manage status
#   sudo manage backend start
#   sudo manage caddy restart -y
#   sudo manage frontend sync --delete
#   sudo manage backend logs 100
#   sudo manage duckdns status
# ════════════════════════════════════════════════════════════

set -uo pipefail

REPO="/root/nuevoFinal"
BACKEND_DIR="$REPO/backend"
BACKEND_BIN="$BACKEND_DIR/.venv/bin/uvicorn"
BACKEND_PIDFILE="/var/run/lgmdm-backend.pid"
BACKEND_LOG="/var/log/lgmdm-backend.log"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"

CADDY_BIN="/usr/bin/caddy"
CADDY_CONF="/etc/caddy/Caddyfile"
CADDY_LOG="/var/log/caddy.log"
CADDY_WRAPPER="$REPO/caddy-start.sh"

FRONTEND_SRC="$REPO/frontend"
FRONTEND_DST="/var/www/masteringstudio"
FRONTEND_SYNC="$REPO/frontend-sync.sh"

DUCKDNS_TIMER="duckdns-update.timer"
DUCKDNS_SERVICE="duckdns-update.service"
DUCKDNS_LOG="/var/log/duckdns.log"

C_GREEN="\033[1;32m"; C_RED="\033[1;31m"; C_YELLOW="\033[1;33m"
C_BLUE="\033[1;34m"; C_BOLD="\033[1m"; C_RESET="\033[0m"

# ── Helpers ─────────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
Usage: sudo manage <service> <action> [opts]
       sudo manage status
       sudo manage --help

Services: backend | caddy | frontend | duckdns
Actions:  start | stop | restart | status | logs [N] | sync (frontend only)

Opciones:
  -y, --yes     No pedir confirmación en stop/restart
  -h, --help    Mostrar esta ayuda
  -f, --follow  Para logs: seguir agregando líneas (equivalente a N=0)

Ejemplos:
  sudo manage status
  sudo manage backend start
  sudo manage caddy restart -y
  sudo manage frontend sync --delete
  sudo manage backend logs 100
  sudo manage duckdns status

Nota: 'manage' es symlink en /usr/local/bin/ que apunta a
/root/nuevoFinal/manage.sh. Otros scripts disponibles globalmente:
  frontend-sync   /root/nuevoFinal/frontend-sync.sh
  install-duckdns /root/nuevoFinal/install-duckdns.sh
EOF
}

confirm() {
  local msg="$1"
  if $ASSUME_YES; then return 0; fi
  # Auto-asumir yes si stdin no es TTY (ej: pipe, cron, shell no interactiva)
  if [ ! -t 0 ]; then
    log "(auto-yes: stdin no interactivo) $msg"
    return 0
  fi
  read -r -p "$msg [y/N] " ans
  case "$ans" in y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
}

log() {
  echo -e "${C_BLUE}[$(date '+%H:%M:%S')]${C_RESET} $*"
}

ok()   { echo -e "${C_GREEN}✓${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}⚠${C_RESET} $*"; }
err()  { echo -e "${C_RED}✗${C_RESET} $*" >&2; }

is_root() { [ "$(id -u)" -eq 0 ]; }

require_root() {
  if ! is_root; then
    err "Este script necesita root. Reintentá con sudo."
    exit 1
  fi
}

ensure_log_dir() {
  mkdir -p "$(dirname "$BACKEND_LOG")" 2>/dev/null || true
}

# ── BACKEND ─────────────────────────────────────────────────────────────────

backend_pid() {
  if [ -f "$BACKEND_PIDFILE" ]; then
    cat "$BACKEND_PIDFILE" 2>/dev/null
  fi
}

backend_is_running() {
  local pid; pid=$(backend_pid)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

backend_start() {
  if backend_is_running; then
    warn "Backend ya está corriendo (PID $(backend_pid))"
    return 0
  fi
  if [ ! -x "$BACKEND_BIN" ]; then
    err "uvicorn no encontrado: $BACKEND_BIN"
    return 1
  fi
  log "Arrancando backend (uvicorn en $BACKEND_HOST:$BACKEND_PORT)..."
  ensure_log_dir
  cd "$BACKEND_DIR"
  nohup "$BACKEND_BIN" app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
    >> "$BACKEND_LOG" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "$BACKEND_PIDFILE"
  disown 2>/dev/null || true
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    ok "Backend arrancado (PID $pid, log: $BACKEND_LOG)"
  else
    err "Backend falló al arrancar. Últimas líneas del log:"
    tail -10 "$BACKEND_LOG" >&2
    rm -f "$BACKEND_PIDFILE"
    return 1
  fi
}

backend_stop() {
  if ! backend_is_running; then
    warn "Backend no está corriendo"
    rm -f "$BACKEND_PIDFILE"
    return 0
  fi
  local pid; pid=$(backend_pid)
  log "Deteniendo backend (PID $pid)..."
  kill -TERM "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "No respondió a SIGTERM, enviando SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$BACKEND_PIDFILE"
  ok "Backend detenido"
}

backend_status() {
  if backend_is_running; then
    local pid; pid=$(backend_pid)
    local port; port=$(ss -tlnp 2>/dev/null | grep ":$BACKEND_PORT " | head -1 | awk '{print $1}')
    ok "Backend ${C_GREEN}running${C_RESET} (PID $pid, $BACKEND_HOST:$BACKEND_PORT $port)"
  else
    err "Backend ${C_RED}stopped${C_RESET}"
  fi
}

backend_logs() {
  ensure_log_dir
  if [ ! -s "$BACKEND_LOG" ]; then err "log vacío: $BACKEND_LOG"; return 1; fi
  local n="${1:-50}"
  if [ "$n" = "0" ] || [ "${FOLLOW:-0}" = "1" ]; then
    tail -F "$BACKEND_LOG"
  else
    tail -n "$n" "$BACKEND_LOG"
  fi
}

# ── CADDY ───────────────────────────────────────────────────────────────────

caddy_is_running() {
  pgrep -f "caddy run --config $CADDY_CONF" > /dev/null 2>&1
}

caddy_pid() {
  pgrep -f "caddy run --config $CADDY_CONF" | head -1
}

caddy_start() {
  if caddy_is_running; then
    warn "Caddy ya está corriendo (PID $(caddy_pid))"
    return 0
  fi
  log "Arrancando caddy..."
  if [ -x "$CADDY_WRAPPER" ]; then
    bash "$CADDY_WRAPPER" 2>&1 | tail -5
  else
    nohup "$CADDY_BIN" run --config "$CADDY_CONF" >> "$CADDY_LOG" 2>&1 < /dev/null &
    disown 2>/dev/null || true
  fi
  sleep 2
  if caddy_is_running; then
    ok "Caddy arrancado (PID $(caddy_pid))"
  else
    err "Caddy falló al arrancar. Últimas líneas del log:"
    tail -10 "$CADDY_LOG" >&2
    return 1
  fi
}

caddy_stop() {
  if ! caddy_is_running; then
    warn "Caddy no está corriendo"
    return 0
  fi
  local pid; pid=$(caddy_pid)
  log "Deteniendo caddy (PID $pid)..."
  kill -TERM "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "No respondió a SIGTERM, SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
  fi
  ok "Caddy detenido"
}

caddy_status() {
  if caddy_is_running; then
    local pid; pid=$(caddy_pid)
    local ports; ports=$(ss -tlnp 2>/dev/null | grep -E ":(80|443)\b" | wc -l)
    ok "Caddy ${C_GREEN}running${C_RESET} (PID $pid, ports 80/443 listening: $ports)"
  else
    err "Caddy ${C_RED}stopped${C_RESET}"
  fi
}

caddy_logs() {
  if [ ! -s "$CADDY_LOG" ]; then err "log vacío: $CADDY_LOG"; return 1; fi
  local n="${1:-50}"
  if [ "$n" = "0" ] || [ "${FOLLOW:-0}" = "1" ]; then
    tail -F "$CADDY_LOG"
  else
    tail -n "$n" "$CADDY_LOG"
  fi
}

# ── FRONTEND ─────────────────────────────────────────────────────────────────

frontend_last_sync() {
  # Best effort: tiempo de modificación del index.html en dst
  stat -c '%y' "$FRONTEND_DST/index.html" 2>/dev/null | cut -d. -f1
}

frontend_status() {
  if [ -f "$FRONTEND_DST/index.html" ]; then
    local files; files=$(find "$FRONTEND_DST" -type f | wc -l)
    ok "Frontend ${C_GREEN}deployed${C_RESET} ($files files, last sync: $(frontend_last_sync))"
  else
    err "Frontend ${C_RED}no deployado${C_RESET} ($FRONTEND_DST no existe)"
  fi
}

frontend_sync() {
  if [ -x "$FRONTEND_SYNC" ]; then
    bash "$FRONTEND_SYNC" "$@"
  else
    err "sync script no encontrado: $FRONTEND_SYNC"
    return 1
  fi
}

# ── DUCKDNS ──────────────────────────────────────────────────────────────────

duckdns_is_running() {
  systemctl is-active --quiet "$DUCKDNS_TIMER" 2>/dev/null
}

duckdns_status() {
  if duckdns_is_running; then
    ok "DuckDNS timer ${C_GREEN}active${C_RESET}"
    systemctl list-timers "$DUCKDNS_TIMER" --no-pager 2>&1 | tail -2
    echo ""
    log "Última corrida:"
    tail -1 "$DUCKDNS_LOG" 2>/dev/null || echo "(sin log)"
  else
    err "DuckDNS timer ${C_RED}inactive${C_RESET}"
  fi
}

duckdns_logs() {
  local n="${1:-50}"
  if [ "$n" = "0" ] || [ "${FOLLOW:-0}" = "1" ]; then
    journalctl -u "$DUCKDNS_SERVICE" -f
  else
    journalctl -u "$DUCKDNS_SERVICE" -n "$n" --no-pager
  fi
}

duckdns_start() {
  log "Habilitando timer $DUCKDNS_TIMER..."
  systemctl enable --now "$DUCKDNS_TIMER" 2>&1 | tail -2
  ok "DuckDNS timer activado"
}

duckdns_stop() {
  log "Deteniendo timer $DUCKDNS_TIMER..."
  systemctl stop "$DUCKDNS_TIMER" 2>&1 | tail -2
  ok "DuckDNS timer detenido"
}

# ── Dispatch ────────────────────────────────────────────────────────────────

service_status() {
  echo ""
  echo -e "${C_BOLD}=== Estado de servicios ===${C_RESET}"
  backend_status
  caddy_status
  frontend_status
  duckdns_status
  echo ""
}

dispatch() {
  local svc="$1" action="$2"
  shift 2 || true

  case "$svc" in
    backend)
      case "$action" in
        start)   require_root; backend_start ;;
        stop)    require_root; confirm "¿Detener backend?" && backend_stop ;;
        restart) require_root; confirm "¿Reiniciar backend?" && { backend_stop; sleep 1; backend_start; } ;;
        status)  backend_status ;;
        logs)    backend_logs "${1:-50}" ;;
        *)       err "acción inválida para backend: $action"; usage; exit 1 ;;
      esac ;;
    caddy)
      case "$action" in
        start)   require_root; caddy_start ;;
        stop)    require_root; confirm "¿Detener caddy?" && caddy_stop ;;
        restart) require_root; confirm "¿Reiniciar caddy?" && { caddy_stop; sleep 1; caddy_start; } ;;
        status)  caddy_status ;;
        logs)    caddy_logs "${1:-50}" ;;
        *)       err "acción inválida para caddy: $action"; usage; exit 1 ;;
      esac ;;
    frontend)
      case "$action" in
        sync)    require_root; frontend_sync "$@" ;;
        status)  frontend_status ;;
        *)       err "acción inválida para frontend: $action (esperado: sync|status)"; exit 1 ;;
      esac ;;
    duckdns)
      case "$action" in
        start)   require_root; duckdns_start ;;
        stop)    require_root; confirm "¿Detener duckdns timer?" && duckdns_stop ;;
        status)  duckdns_status ;;
        logs)    duckdns_logs "${1:-50}" ;;
        *)       err "acción inválida para duckdns: $action (esperado: start|stop|status|logs)"; exit 1 ;;
      esac ;;
    *)
      err "servicio inválido: $svc"
      usage
      exit 1
      ;;
  esac
}

# ── Main ─────────────────────────────────────────────────────────────────────

ASSUME_YES=false
FOLLOW=0

# Parse args
if [ $# -eq 0 ]; then usage; exit 0; fi

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes)  ASSUME_YES=true; shift ;;
    -f|--follow) FOLLOW=1; shift ;;
    status)
      # Solo tratar como "overview" si es el ÚNICO argumento.
      # Si hay más args (ej: 'backend status'), va al dispatch normal.
      if [ "${#ARGS[@]}" -eq 0 ] && [ $# -eq 1 ]; then
        service_status
        exit 0
      else
        ARGS+=("$1")
        shift
      fi
      ;;
    *)         ARGS+=("$1"); shift ;;
  esac
done

if [ "${#ARGS[@]}" -lt 2 ]; then
  usage
  exit 1
fi

dispatch "${ARGS[0]}" "${ARGS[1]}" "${ARGS[@]:2}"
