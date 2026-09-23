#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# install-duckdns.sh — Update client + firewall para masteringstudio.duckdns.org
# USO:  sudo bash ./install-duckdns.sh
#       (pide el token de duckdns.org interactivamente — no queda en history)
# IDEMPOTENTE: se puede correr varias veces sin romper.
# ════════════════════════════════════════════════════════════

set -euo pipefail

DOMAIN="masteringstudio"
SCRIPT_PATH="/usr/local/bin/duckdns-update.sh"
SERVICE_PATH="/etc/systemd/system/duckdns-update.service"
TIMER_PATH="/etc/systemd/system/duckdns-update.timer"

# ── Token (prompt interactivo, con fallback a env var y CLI arg) ──
if [ -n "${DUCKDNS_TOKEN:-}" ]; then
  TOKEN="$DUCKDNS_TOKEN"
  echo "[token tomado de variable de entorno \$DUCKDNS_TOKEN]"
elif [ -n "${1:-}" ]; then
  TOKEN="$1"
  echo "[token tomado de argumento CLI]"
else
  echo ""
  echo "╔════════════════════════════════════════════════════════════╗"
  echo "║  DuckDNS — token de autenticación                          ║"
  echo "╠════════════════════════════════════════════════════════════╣"
  echo "║ 1. Ir a https://www.duckdns.org/ y loguearse             ║"
  echo "║    (GitHub / Google / Reddit)                              ║"
  echo "║ 2. Copiar el token que aparece arriba a la derecha       ║"
  echo "║    (formato: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee)         ║"
  echo "║ 3. Pegarlo abajo. El input se oculta por seguridad.      ║"
  echo "╚════════════════════════════════════════════════════════════╝"
  echo ""
  while [ -z "${TOKEN:-}" ]; do
    read -r -s -p "Token: " TOKEN
    echo ""
    if [ -z "$TOKEN" ]; then
      echo "(vacío — reintentá)"
    fi
  done
fi

# ── Confirmación ──
echo ""
echo "Dominio a actualizar: ${DOMAIN}.duckdns.org"
echo "IP actual del server:  $(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo '(no se pudo detectar)')"
echo ""
read -r -p "¿Continuar con la instalación? [y/N] " OK
case "$OK" in
  y|Y|yes|Yes|YES) ;;
  *) echo "Cancelado."; exit 0 ;;
esac

# ── 1. Update script (curl al API de DuckDNS) ──
echo "[1/4] Creando update script..."
cat > "$SCRIPT_PATH" <<EOF
#!/usr/bin/env bash
# Auto-generado por install-duckdns.sh — no editar a mano.
DOMAIN="${DOMAIN}"
TOKEN="${TOKEN}"
TS="\$(date -Iseconds)"
HTTP=\$(curl -fsS "https://www.duckdns.org/update?domains=\${DOMAIN}&token=\${TOKEN}&ip=" \\
  -o /var/log/duckdns.log -w "%{http_code}" 2>&1) || HTTP="ERR"
echo "[\${TS}] domain=\${DOMAIN} http=\${HTTP}" >> /var/log/duckdns.log
EOF
chmod 700 "$SCRIPT_PATH"

# ── 2. systemd service + timer ──
echo "[2/4] Creando systemd service + timer..."
cat > "$SERVICE_PATH" <<'EOF'
[Unit]
Description=Update masteringstudio.duckdns.org IP en DuckDNS
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/duckdns-update.sh
Nice=19
EOF

cat > "$TIMER_PATH" <<'EOF'
[Unit]
Description=Trigger DuckDNS update cada 5 minutos

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=false

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now duckdns-update.timer

# ── 3. ufw ──
echo "[3/4] Abriendo puertos 80/443 en ufw..."
ufw allow 80/tcp  comment 'Caddy HTTP (ACME challenge + redirect HTTPS)'
ufw allow 443/tcp comment 'Caddy HTTPS'

# ── 4. Update inicial ──
echo "[4/4] Disparando update inicial..."
"$SCRIPT_PATH"

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║ ✓ Instalación completa                                  ║"
echo "╠════════════════════════════════════════════════════════════╣"
echo "║ - update script:  $SCRIPT_PATH"
echo "║ - systemd timer:  duckdns-update.timer (cada 5 min)"
echo "║ - próxima corr.:  systemctl list-timers duckdns-update.timer"
echo "║ - logs:           journalctl -u duckdns-update.service -n 50"
echo "║ - manual update:  systemctl start duckdns-update.service"
echo "║"
echo "║ Próximo paso: reiniciar Caddy para emitir cert Let's Encrypt:"
echo "║   pkill -f 'caddy run' && /root/nuevoFinal/caddy-start.sh"
echo "║"
echo "║ Verificar:"
echo "║   curl -I https://masteringstudio.duckdns.org"
echo "╚════════════════════════════════════════════════════════════╝"
