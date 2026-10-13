#!/usr/bin/env bash
# wa_qr_capture.sh — capture the WhatsApp "link a device" QR from the emulator
# and pull it to the driver host so a human can scan it with the registered
# phone. Zero ban risk: this only reads pixels off the guest screen.
#
# Usage (from cobrador, the driver host):
#   bash tools/whatsapp/wa_qr_capture.sh [out.png]
#
# Requires: the emulator on dq05 is up (adb-tunnel units active) and WhatsApp
# is on its "Link a device" QR screen.
set -euo pipefail

OUT="${1:-$HOME/wa-link-qr-$(date +%Y%m%d-%H%M%S).png}"
VENV_PY="/home/c03rad0r/wa_u2_venv/bin/python"
U2="/tmp/u2_probe.py"
DQ05="dq05"

echo "=== 1. confirm the guest is reachable ==="
ssh -o ConnectTimeout=8 "$DQ05" 'export PATH=$PATH:$HOME/Android/Sdk/platform-tools; adb devices | grep -q emulator-5554 || { echo "FATAL: emulator-5554 not visible on dq05"; exit 1; }; echo "guest reachable"'

echo "=== 2. confirm the QR screen is showing ==="
ssh -o ConnectTimeout=8 "$DQ05" "export PATH=\$PATH:\$HOME/Android/Sdk/platform-tools; adb shell dumpsys window 2>/dev/null | grep mCurrentFocus | head -1"

echo "=== 3. screenshot + pull ==="
ssh -o ConnectTimeout=8 "$DQ05" 'export PATH=$PATH:$HOME/Android/Sdk/platform-tools; adb exec-out screencap -p > /tmp/wa-qr.png && ls -la /tmp/wa-qr.png'
scp -q "$DQ05:/tmp/wa-qr.png" "$OUT"
echo "=== QR captured: $OUT ==="
echo ""
echo "NEXT: send this image to the person with the registered phone;"
echo "they scan it in WhatsApp -> Settings -> Linked devices -> Link a device."
echo "      (If the screen shows a 63-char pairing code instead of a QR,"
echo "       read it aloud / paste it to them — WhatsApp accepts either.)"
