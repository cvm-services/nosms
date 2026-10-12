#!/usr/bin/env bash
# micronuts-vps2-deploy.sh — put the micronuts Cashu mint on vps2 as the CVM's
# PUBLIC settlement mint, reachable by a browser PWA.
#
# Runs ON testserver2 (vps2). Idempotent: safe to re-run.
#
#   mint  : ~/micronuts/bin/mint_server        (child of the adapter)
#   adapter: :3338  (localhost only — Caddy terminates TLS in front)
#   public : https://mint-test.orangesync.tech  (Caddy reverse_proxy + CORS)
#
# CORS is REQUIRED and comes from Caddy, not the adapter: the adapter is an
# axum app with no CORS layer, so a browser fetch from the PWA origin would be
# blocked. See the "no CORS headers" probe in docs/CVM-MINT-DECISION.md.
set -euo pipefail

ROOT="$HOME/micronuts"
BIN="$ROOT/bin"
STATE="$ROOT/state"
SEED_FILE="$STATE/keyset.seed"
PORT=3338

mkdir -p "$BIN" "$STATE"

# --- entropic keyset seed ----------------------------------------------------
# 32 bytes of real entropy. A state file without this prints a loud warning and
# derives the demo keyset from a PUBLIC seed — never custody value with that.
if [ ! -f "$SEED_FILE" ]; then
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$SEED_FILE"
  chmod 600 "$SEED_FILE"
  echo "generated keyset seed"
fi

# --- systemd user unit (the adapter spawns mint_server as its child) ---------
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/micronuts-mint.service" <<EOF
[Unit]
Description=micronuts Cashu mint (public settlement mint for the SMS CVM)
Documentation=https://github.com/Amperstrand/micronuts

[Service]
Type=simple
WorkingDirectory=$ROOT
Environment=MICRONUTS_ADAPTER_BIND=127.0.0.1
Environment=MICRONUTS_ADAPTER_PORT=$PORT
Environment=MICRONUTS_MINT_BIN=$BIN/mint_server
Environment=MICRONUTS_MINT_STATE_FILE=$STATE/mint-state.bin
Environment=MICRONUTS_RESERVE_STATE_FILE=$STATE/reserve-state.bin
Environment=MICRONUTS_MINT_KEYSET_SEED=%SECRET%
ExecStart=$BIN/micronuts-audit-adapter
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# inject the seed without leaving it in the unit file
SEED=$(cat "$SEED_FILE")
sed -i "s|Environment=MICRONUTS_MINT_KEYSET_SEED=%SECRET%|Environment=MICRONUTS_MINT_KEYSET_SEED=$SEED|" \
  "$UNIT_DIR/micronuts-mint.service"
chmod 600 "$UNIT_DIR/micronuts-mint.service"

systemctl --user daemon-reload
systemctl --user enable --now micronuts-mint
# enable --now does NOT restart an already-running unit; force it so new env sticks
systemctl --user restart micronuts-mint
sleep 3

echo "--- unit state ---"
systemctl --user is-active micronuts-mint
curl -s -m 5 "http://127.0.0.1:$PORT/v1/keysets" | head -c 200
echo
echo "--- keyset id ---"
curl -s -m 5 "http://127.0.0.1:$PORT/v1/keysets" | grep -o '"id":"[0-9a-f]*"' | head -1
