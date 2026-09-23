#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# manage.sh — Service manager interactivo para LGMDM
# USO INTERACTIVO (menú numerado):
#   sudo manage                          # entra al menú
#   sudo manage -i | --interactive       # alias
#
# USO DIRECTO (subcommand):
#   sudo manage <service> <action> [opts]
#   sudo manage status
#   sudo manage --help
#
# El script vive en /root/nuevoFinal/manage.sh pero hay un symlink
# en /usr/local/bin/manage — funciona globalmente sin path.
# ════════════════════════════════════════════════════════════

set -uo pipefail

REPO="/root/nuevoFinal"
BACKEND_DIR="$REPO/backend"
BACKEND_BIN="$BACKEND_DIR/.venv/bin/uvicorn"
BACKEND_PIDFILE="/var/run/lgmdm-backend.pid"
BACKEND_LOG="/var/log/lgmdm-backend.log"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
BACKEND_UNIT="lgmdm-backend.service"
CADDY_UNIT="caddy.service"
BACKEND_UNIT="lgmdm-backend.service"
CADDY_UNIT="caddy.service"

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
Usage (interactivo — menú numerado):
  sudo manage                          # abre el menú interactivo
  sudo manage -i | --interactive

Usage (directo — subcommand):
  sudo manage <service> <action> [opts]
  sudo manage status
  sudo manage --help

Services: backend | caddy | frontend | duckdns
Actions:  start | stop | restart | status | logs [N] | sync (frontend only)

Opciones:
  -y, --yes     No pedir confirmación en stop/restart
  -h, --help    Mostrar esta ayuda
  -f, --follow  Para logs: seguir agregando líneas (N=0)
  -i, --interactive  Forzar menú interactivo

Ejemplos directos:
  sudo manage status
  sudo manage backend start
  sudo manage caddy restart -y
  sudo manage frontend sync --delete
  sudo manage backend logs 100

Nota: 'manage' es symlink en /usr/local/bin/ → /root/nuevoFinal/manage.sh
Otros scripts globales: frontend-sync, install-duckdns
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
  # Fuente de verdad: systemd (si la unit existe). Fallback: PID file legacy.
  if systemctl list-unit-files "$BACKEND_UNIT" >/dev/null 2>&1 \
     && systemctl cat "$BACKEND_UNIT" >/dev/null 2>&1; then
    systemctl is-active --quiet "$BACKEND_UNIT"
    return $?
  fi
  local pid; pid=$(backend_pid)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

backend_start() {
  if backend_is_running; then
    warn "Backend ya está corriendo (PID $(backend_pid))"
    return 0
  fi
  # Ruta systemd (preferida — auto-restart + boot)
  if systemctl cat "$BACKEND_UNIT" >/dev/null 2>&1; then
    log "Arrancando backend (systemd: $BACKEND_UNIT)..."
    systemctl start "$BACKEND_UNIT"
    sleep 1
    if systemctl is-active --quiet "$BACKEND_UNIT"; then
      local pid; pid=$(systemctl show -p MainPID --value "$BACKEND_UNIT")
      echo "$pid" > "$BACKEND_PIDFILE" 2>/dev/null || true
      ok "Backend arrancado (PID $pid, log: $BACKEND_LOG)"
      return 0
    fi
    err "Backend falló al arrancar (systemd). Últimas líneas:"
    journalctl -u "$BACKEND_UNIT" -n 15 --no-pager >&2
    return 1
  fi
  # Fallback legacy nohup (sin unit)
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
  if systemctl cat "$BACKEND_UNIT" >/dev/null 2>&1 \
     && systemctl is-active --quiet "$BACKEND_UNIT"; then
    log "Deteniendo backend (systemd: $BACKEND_UNIT)..."
    systemctl stop "$BACKEND_UNIT"
    rm -f "$BACKEND_PIDFILE"
    ok "Backend detenido"
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
    if [ -z "$pid" ] && systemctl cat "$BACKEND_UNIT" >/dev/null 2>&1; then
      pid=$(systemctl show -p MainPID --value "$BACKEND_UNIT")
    fi
    local port; port=$(ss -tlnp 2>/dev/null | grep ":$BACKEND_PORT " | head -1 | awk '{print $1}')
    local via="nohup"
    systemctl is-active --quiet "$BACKEND_UNIT" 2>/dev/null && via="systemd"
    ok "Backend ${C_GREEN}running${C_RESET} (PID $pid, $via, $BACKEND_HOST:$BACKEND_PORT $port)"
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
  # Fuente de verdad: systemd; fallback pgrep para huérfanos legacy.
  systemctl is-active --quiet "$CADDY_UNIT" 2>/dev/null && return 0
  pgrep -f "caddy run --config $CADDY_CONF" > /dev/null 2>&1 \
    || pgrep -f "caddy run --environ --config $CADDY_CONF" > /dev/null 2>&1
}

caddy_pid() {
  if systemctl is-active --quiet "$CADDY_UNIT" 2>/dev/null; then
    systemctl show -p MainPID --value "$CADDY_UNIT"
    return
  fi
  pgrep -f "caddy run --config $CADDY_CONF" | head -1
}

caddy_start() {
  if caddy_is_running; then
    warn "Caddy ya está corriendo (PID $(caddy_pid))"
    return 0
  fi
  log "Arrancando caddy (systemd: $CADDY_UNIT)..."
  systemctl start "$CADDY_UNIT"
  sleep 2
  if caddy_is_running; then
    ok "Caddy arrancado (PID $(caddy_pid))"
  else
    err "Caddy falló al arrancar. journal:"
    journalctl -u "$CADDY_UNIT" -n 15 --no-pager >&2
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
  if systemctl is-active --quiet "$CADDY_UNIT" 2>/dev/null; then
    systemctl stop "$CADDY_UNIT"
    ok "Caddy detenido"
    return 0
  fi
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
    local via="systemd"
    systemctl is-active --quiet "$CADDY_UNIT" 2>/dev/null || via="huérfano"
    ok "Caddy ${C_GREEN}running${C_RESET} (PID $pid, $via, ports 80/443 listening: $ports)"
  else
    err "Caddy ${C_RED}stopped${C_RESET}"
  fi
}

caddy_logs() {
  local n="${1:-50}"
  if systemctl is-active --quiet "$CADDY_UNIT" 2>/dev/null; then
    if [ "$n" = "0" ] || [ "${FOLLOW:-0}" = "1" ]; then
      journalctl -u "$CADDY_UNIT" -n 0 -f
    else
      journalctl -u "$CADDY_UNIT" -n "$n" --no-pager
    fi
    return 0
  fi
  if [ ! -s "$CADDY_LOG" ]; then err "log vacío: $CADDY_LOG"; return 1; fi
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

# ── Modo interactivo (menú numerado) ────────────────────────────────────────
# Cuando se invoca sin argumentos (o con -i/--interactive), muestra un
# menú numerado. Elige una opción con el número correspondiente.

interactive_mode() {
  # No hay TTY → no podemos mostrar menú interactivo
  if [ ! -t 0 ]; then
    warn "stdin no es TTY — el menú interactivo requiere terminal."
    warn "Usá 'manage <svc> <action>' directamente."
    return 0
  fi

  local choice
  while :; do
    printf '\033[2J\033[H'  # clear
    echo -e "${C_BOLD}══════════════════════════════════════════════════${C_RESET}"
    echo -e "${C_BOLD}  LGMDM — Service Manager${C_RESET}"
    echo -e "${C_BOLD}══════════════════════════════════════════════════${C_RESET}"
    echo ""
    echo -e "  ${C_BOLD}BACKEND (FastAPI :8000)${C_RESET}"
    echo -e "    ${C_GREEN}1${C_RESET}) Iniciar backend"
    echo -e "    ${C_GREEN}2${C_RESET}) Detener backend"
    echo -e "    ${C_GREEN}3${C_RESET}) Reiniciar backend"
    echo -e "    ${C_GREEN}4${C_RESET}) Estado backend"
    echo -e "    ${C_GREEN}5${C_RESET}) Ver logs backend"
    echo ""
    echo -e "  ${C_BOLD}CADDY (HTTPS reverse proxy)${C_RESET}"
    echo -e "    ${C_YELLOW}6${C_RESET}) Iniciar caddy"
    echo -e "    ${C_YELLOW}7${C_RESET}) Detener caddy"
    echo -e "    ${C_YELLOW}8${C_RESET}) Reiniciar caddy"
    echo -e "    ${C_YELLOW}9${C_RESET}) Estado caddy"
    echo -e "    ${C_YELLOW}10${C_RESET}) Ver logs caddy"
    echo ""
    echo -e "  ${C_BOLD}FRONTEND (static files)${C_RESET}"
    echo -e "    ${C_BLUE}11${C_RESET}) Sincronizar frontend a /var/www"
    echo -e "    ${C_BLUE}12${C_RESET}) Estado frontend"
    echo ""
    echo -e "  ${C_BOLD}DUCKDNS (DDNS timer)${C_RESET}"
    echo -e "    ${C_RED}13${C_RESET}) Iniciar timer DuckDNS"
    echo -e "    ${C_RED}14${C_RESET}) Detener timer DuckDNS"
    echo -e "    ${C_RED}15${C_RESET}) Estado DuckDNS"
    echo -e "    ${C_RED}16${C_RESET}) Ver logs DuckDNS"
    echo ""
    echo -e "  ${C_BOLD}GENERAL${C_RESET}"
    echo -e "    ${C_BOLD}17${C_RESET}) Estado de todos los servicios"
    echo ""
    echo -e "    ${C_RED}0${C_RESET}) Salir"
    echo ""
    echo -e "${C_BOLD}══════════════════════════════════════════════════${C_RESET}"

    read -r -p "  Elegí una opción: " choice || break

    case "$choice" in
      0)  echo ""; echo "  Chau."; return 0 ;;
      1)  require_root; backend_start ;;
      2)  require_root; confirm "¿Detener backend?" && backend_stop ;;
      3)  require_root; confirm "¿Reiniciar backend?" && { backend_stop; sleep 1; backend_start; } ;;
      4)  echo ""; backend_status ;;
      5)  echo ""; backend_logs 50; echo ""; read -r -p "  Enter para continuar..." _ ;;
      6)  require_root; caddy_start ;;
      7)  require_root; confirm "¿Detener caddy?" && caddy_stop ;;
      8)  require_root; confirm "¿Reiniciar caddy?" && { caddy_stop; sleep 1; caddy_start; } ;;
      9)  echo ""; caddy_status ;;
      10) echo ""; caddy_logs 50; echo ""; read -r -p "  Enter para continuar..." _ ;;
      11) require_root; frontend_sync --delete ;;
      12) echo ""; frontend_status ;;
      13) require_root; duckdns_start ;;
      14) require_root; confirm "¿Detener timer DuckDNS?" && duckdns_stop ;;
      15) echo ""; duckdns_status ;;
      16) echo ""; duckdns_logs 50; echo ""; read -r -p "  Enter para continuar..." _ ;;
      17) service_status ;;
      *)  echo ""; warn "Opción inválida: $choice" ;;
    esac

    echo ""
    [ "$choice" != "5" ] && [ "$choice" != "10" ] && [ "$choice" != "16" ] && \
      read -r -p "  Enter para volver al menú..." _ || true
  done
  return 0
}

# Parse args
if [ $# -eq 0 ]; then interactive_mode; exit 0; fi

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes)  ASSUME_YES=true; shift ;;
    -f|--follow) FOLLOW=1; shift ;;
    -i|--interactive) interactive_mode; exit 0 ;;
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
