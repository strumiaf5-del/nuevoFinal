#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# caddy-start.sh — wrapper para arrancar caddy sin colgar la shell
# Uso: ./caddy-start.sh
# Logs: /var/log/caddy.log
# ════════════════════════════════════════════════════════════

set -e

CONF="${Caddyfile:-/etc/caddy/Caddyfile}"
LOG="${LOG:-/var/log/caddy.log}"

# Validar antes de arrancar
if ! caddy validate --config "$CONF" > /dev/null 2>&1; then
    echo "ERROR: Caddyfile inválido:" >&2
    caddy validate --config "$CONF" >&2
    exit 1
fi

# Si ya está corriendo, reload
if pgrep -f "caddy run" > /dev/null; then
    echo "Caddy ya está corriendo. Reload config..."
    caddy reload --config "$CONF" --address 127.0.0.1:2019 || true
    exit 0
fi

# Arrancar detached
nohup caddy run --config "$CONF" >> "$LOG" 2>&1 < /dev/null &
CADDY_PID=$!
disown 2>/dev/null || true
sleep 1
echo "Caddy started (PID $CADDY_PID). Logs en $LOG"
echo "  - Stop: pkill -f 'caddy run'"
echo "  - Status: ps aux | grep 'caddy run'"
echo "  - Reload: caddy reload --config $CONF --address 127.0.0.1:2019"
