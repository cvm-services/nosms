#!/usr/bin/env bash
# deploy/micronuts-mint-deploy.sh — IaC bring-up for the micronuts Cashu mint
# (Amperstrand) as the SMS CVM's test settlement mint.
#
# WHAT THIS BRINGS UP (idempotent — safe to re-run):
#   micronuts-mint      systemd user unit   mint_server (stdio CBOR-RPC core)
#   micronuts-adapter   systemd user unit   axum REST bridge on 127.0.0.1:3338
#                                         (default 3030 avoided — nosms e2e
#                                         scripts live on 3030)
#
# Money rules honoured (micronuts AGENTS.md): unset MICRONUTS_UPSTREAM_MINT =
# auto-settling FakeWallet = free rein. Signet mode exists but requires the
# remote CLN node (out of scope for this bring-up).
#
# State layout (durable, survives restarts):
#   ~/.hermes/state/micronuts/mint-state.bin        MICRONUTS_MINT_STATE_FILE
#   ~/.hermes/state/micronuts/reserve-state.bin     MICRONUTS_RESERVE_STATE_FILE
#   ~/.hermes/state/micronusts/mint-keyset-seed      MICRONUTS_MINT_KEYSET_SEED (0600)
#
# Usage:  bash deploy/micronuts-mint-deploy.sh
set -euo pipefail

REPO="${REPO:-$HOME/repos/micronuts}"
STATE_DIR="$HOME/.hermes/state/micronuts"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PORT="${MICRONUTS_ADAPTER_PORT:-3338}"
BIND="${MICRONUTS_ADAPTER_BIND:-127.0.0.1}"

mkdir -p "$STATE_DIR" "$UNIT_DIR"
chmod 700 "$STATE_DIR"

# --- 1. entropic keyset seed (once) ------------------------------------------
SEED_FILE="$STATE_DIR/mint-keyset-seed"
if [[ ! -s "$SEED_FILE" ]]; then
    # 64 hex chars = 32 bytes of entropy; never derived from anything known.
    SEED="$(od -An -tx1 -N32 /dev/urandom | tr -d ' \n')"
    printf '%s' "$SEED" > "$SEED_FILE"
    chmod 600 "$SEED_FILE"
    echo "[deploy] wrote new keyset seed (0600, 32 bytes entropy)"
else
    echo "[deploy] keyset seed already present"
fi
SEED="$(cat "$SEED_FILE")"

# --- 2. find the built binaries ----------------------------------------------
# NOTE: if a global CARGO_TARGET_DIR is set the binaries land outside the repo.
BIN_DIR="${CARGO_TARGET_DIR:-$REPO/target}/debug"
MINT_BIN="$BIN_DIR/mint_server"
ADAPTER_BIN="$BIN_DIR/micronuts-audit-adapter"
for b in "$MINT_BIN" "$ADAPTER_BIN"; do
    [[ -x "$b" ]] || { echo "[deploy] FATAL: missing binary $b (cargo build first)"; exit 1; }
done

# --- 3. systemd user units ---------------------------------------------------
# Topology (verified live): micronuts-audit-adapter SPAWNS mint_server as its
# own child process (stdio CBOR-RPC) — there is no standalone mint unit.
# Therefore ALL mint env vars must be set on the ADAPTER unit; the child
# inherits them.
cat > "$UNIT_DIR/micronuts-adapter.service" <<EOF
[Unit]
Description=micronuts Cashu mint (adapter :$PORT + spawned mint_server child)
After=network.target

[Service]
Type=simple
ExecStart=$ADAPTER_BIN
Environment=MICRONUTS_ADAPTER_PORT=$PORT
Environment=MICRONUTS_ADAPTER_BIND=$BIND
Environment=MICRONUTS_MINT_BIN=$MINT_BIN
# Mint-core knobs — inherited by the spawned mint_server child:
Environment=MICRONUTS_MINT_STATE_FILE=$STATE_DIR/mint-state.bin
Environment=MICRONUTS_RESERVE_STATE_FILE=$STATE_DIR/reserve-state.bin
Environment=MICRONUTS_RESERVE_BOOTSTRAP_SATS=1000
Environment=MICRONUTS_MINT_KEYSET_SEED=$SEED
# No upstream: FakeWallet auto-settles mint quotes (free rein per AGENTS.md).
# Unset by absence: MICRONUTS_UPSTREAM_MINT, MICRONUTS_UPSTREAM_PAY_TIMEOUT_SECS
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF

# Drop the standalone mint unit if an earlier run created it (the adapter
# owns the mint child; a second stdio mint_server is dead weight).
if [[ -e "$UNIT_DIR/micronuts-mint.service" ]]; then
    systemctl --user disable --now micronuts-mint.service 2>/dev/null || true
    rm -f "$UNIT_DIR/micronuts-mint.service"
    echo "[deploy] removed obsolete standalone micronuts-mint unit (adapter owns the child)"
fi

systemctl --user daemon-reload
systemctl --user enable --now micronuts-adapter.service
sleep 3
systemctl --user --no-pager --lines=5 status micronuts-adapter.service | grep -E 'Active:|●' || true

echo "[deploy] mint REST endpoint: http://$BIND:$PORT"
echo "[deploy] done."