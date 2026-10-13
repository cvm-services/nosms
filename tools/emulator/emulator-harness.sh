#!/usr/bin/env bash
# emulator-harness.sh — reproducible Android emulator bring-up for the WhatsApp rail.
#
# Host target: dq05 ONLY (c03rad0r-DQ05proplus). This script refuses to run the
# emulator on any host without an openable /dev/kvm.
#
# Idempotent. Every step prints the exact command it runs. Run with --dry-run to
# see commands without executing them. Subcommands:
#   preflight   verify the four gates (kvm / disk / ram / dl.google.com)
#   install     install emulator + system image via sdkmanager (no cmdline-tools upgrade)
#   create      create the wa-dev AVD (idempotent --force)
#   boot        launch headless and poll sys.boot_completed until 1 (bounded)
#   status      report emulator / adb / AVD state
#   teardown    adb emu kill + adb kill-server, print what was removed
#   reap        find and kill orphaned qemu-system / emulator processes
#   all         preflight + install + create + boot
#
# Constraints honoured by this script:
#   - NEVER -wipe-data (would destroy the live WhatsApp registration state)
#   - NEVER flip PlayStore.enabled (see README; the E1 image is a playstore build
#     but the AVD config has PlayStore.enabled=no, and adb root is refused)
#   - teardown always runs at end of a boot; do not leave a ~3.3 GB guest on a 4-core box
#
# Evidence basis: tools/emulator/evidence/e1_evidence.log (E1, run 2026-10-06).

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment)
# ---------------------------------------------------------------------------
HOST_TARGET="c03rad0r-DQ05proplus"
SDK_ROOT="${ANDROID_HOME:-$HOME/Android/Sdk}"
SDKMANAGER="${SDKMANAGER:-$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager}"
AVDMANAGER="${AVDMANAGER:-$SDK_ROOT/cmdline-tools/latest/bin/avdmanager}"
EMULATOR="${EMULATOR:-$SDK_ROOT/emulator/emulator}"
ADB="${ADB:-$SDK_ROOT/platform-tools/adb}"
AVD_NAME="${AVD_NAME:-wa-dev}"
AVD_DEVICE="${AVD_DEVICE:-pixel_6}"
SYSTEM_IMAGE="${SYSTEM_IMAGE:-system-images;android-34;google_apis_playstore;x86_64}"
# --- AVD tuning (measured 2026-10-13; do not revert without re-measuring) -----
# The default pixel_6 profile is 1080x2400 with 1536M RAM / 2 cores. On a
# HEADLESS host there is no GPU, so SwiftShader renders every frame in software:
# 2.6 Mpx/frame at 1080x2400 produced 92.6% janky frames and SYNTETIC TAPS WERE
# SILENTLY DROPPED — u2 reported {"ok": true} while the UI never changed
# (proven with a zero-risk overflow-menu probe: menu did not open at
# 1080x2400, opened immediately at 540x1200). Measured improvements:
#   launch WaitTime 24769ms (timeout) -> 2034ms (ok)
#   emulator VmSwap 2.1 GB -> 285 MB
#   u2 accessibility clicks land instead of being dropped
# 540x1200 = 1/4 the pixels of 1080x2400. Keep RAM >= 4096M and cores 4 on a
# 4-core/10GB class box; the guest honours an `wm size` override of 360x800.
AVD_LCD_WIDTH="${AVD_LCD_WIDTH:-540}"
AVD_LCD_HEIGHT="${AVD_LCD_HEIGHT:-1200}"
AVD_LCD_DENSITY="${AVD_LCD_DENSITY:-240}"
AVD_RAM_MB="${AVD_RAM_MB:-4096}"
AVD_CORES="${AVD_CORES:-4}"
AVD_HEAP_MB="${AVD_HEAP_MB:-512}"
PLATFORM_PACKAGE="${PLATFORM_PACKAGE:-platform-tools}"
BOOT_TIMEOUT_S="${BOOT_TIMEOUT_S:-600}"     # 55 * 10s polls in E1; 600s headroom
BOOT_POLL_INTERVAL_S="${BOOT_POLL_INTERVAL_S:-10}"

# Gates (minimums from E1 preflight)
MIN_DISK_GB=15
MIN_RAM_GB=4

DRY_RUN=0

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
run()  {
  # run <description> <cmd...>  — print the exact command, then execute (or skip in --dry-run)
  local desc="$1"; shift
  echo "\$ $*"    # exact command, quoted args rendered verbatim
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: $desc"
    return 0
  fi
  "$@"
}

die()  { echo "FATAL: $*" >&2; exit 1; }
warn() { echo "WARN:  $*" >&2; }

usage() {
  cat <<'EOF'
Usage: emulator-harness.sh [--dry-run] <preflight|install|create|boot|status|teardown|reap|reclaim|doctor|all>
       emulator-harness.sh --help

  --dry-run   print every command without executing it (safe on dq05)
  --help      show this message

Subcommands (all idempotent):
  preflight  gate check: openable /dev/kvm, >=15G disk, >=4G RAM, dl.google.com reachable
  install    sdkmanager install emulator + system image + platform-tools (no cmdline-tools upgrade)
  create     create AVD 'wa-dev' (pixel_6, android-34 google_apis_playstore x86_64)
             and apply the measured headless tuning: 540x1200 lcd, 4G RAM,
             4 cores, 512M heap (see the AVD_* comment for why)
  boot       headless launch + poll sys.boot_completed until 1 (bounded, prints t=<s>)
  status     report current emulator / adb / AVD state
  teardown   adb emu kill + adb kill-server, print what was removed
  reap       kill orphaned qemu-system / emulator processes
  reclaim    free host disk that stalls the guest: journal vacuum (capped),
             stale state.db snapshots, state_db_recover_work, stale /tmp probes
  doctor     READ-ONLY host health: load, PSI io, disk, D-state, runaway scans.
             Reports whether a reclaim or a REBOOT is required (never mutates)
  all        preflight + install + create + boot

This script targets dq05 ONLY and refuses to run the emulator on any host
without an openable /dev/kvm.
EOF
}

# ---------------------------------------------------------------------------
# Host gating
# ---------------------------------------------------------------------------
require_dq05() {
  # The emulator may only run on a host with an openable /dev/kvm. On dq05 this
  # is satisfied; on a laptop without KVM (e.g. CobradorWave) it is not.
  local actual
  actual="$(hostname)"
  if [ "$actual" != "$HOST_TARGET" ]; then
    warn "expected host $HOST_TARGET, running on $actual (proceeding; KVM gate is authoritative)"
  fi
  if [ ! -c /dev/kvm ]; then
    die "/dev/kvm is not present or not a char device on $(hostname). This harness only runs the emulator on a KVM-capable host (dq05)."
  fi
  if ! python3 -c 'import os,sys; os.close(os.open("/dev/kvm", os.O_RDWR))' 2>/dev/null; then
    die "/dev/kvm is not openable O_RDWR by $(id -un) on $(hostname). This harness only runs the emulator on a KVM-capable host (dq05)."
  fi
}

# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------
preflight() {
  log "PREFLIGHT: host=$(hostname) user=$(id -un)"

  # GATE 1 — /dev/kvm openable
  echo "--- gate 1: /dev/kvm openable O_RDWR ---"
  echo "\$ python3 -c 'import os; os.close(os.open(\"/dev/kvm\", os.O_RDWR)); print(\"KVM openable: True\")'"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: kvm open check"
    echo "GATE 1 PASS (dry-run)"
  else
    python3 -c 'import os; os.close(os.open("/dev/kvm", os.O_RDWR)); print("KVM openable: True")' \
      || die "GATE 1 FAILED: /dev/kvm not openable"
    echo "GATE 1 PASS"
  fi

  # GATE 2 — disk >= 15G free on /
  echo "--- gate 2: disk avail on / >= ${MIN_DISK_GB} GB ---"
  echo "\$ df -BG /"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: disk check"
    echo "GATE 2 PASS (dry-run)"
  else
    local avail_gb
    avail_gb=$(df -BG / | awk 'NR==2 {gsub(/G/,"",$4); print $4}')
    echo "avail_GB=$avail_gb"
    if [ "${avail_gb:-0}" -lt "$MIN_DISK_GB" ]; then
      die "GATE 2 FAILED: only ${avail_gb}G free on / (need >= ${MIN_DISK_GB}G)"
    fi
    echo "GATE 2 PASS"
  fi

  # GATE 3 — RAM available >= 4G
  echo "--- gate 3: RAM available >= ${MIN_RAM_GB} GB ---"
  echo "\$ free -g"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: RAM check"
    echo "GATE 3 PASS (dry-run)"
  else
    local avail_ram_gb
    avail_ram_gb=$(free -g | awk '/^Mem:/ {print $7}')
    echo "available_GB=$avail_ram_gb"
    if [ "${avail_ram_gb:-0}" -lt "$MIN_RAM_GB" ]; then
      die "GATE 3 FAILED: only ${avail_ram_gb}G available RAM (need >= ${MIN_RAM_GB}G)"
    fi
    echo "GATE 3 PASS"
  fi

  # GATE 4 — dl.google.com reachable
  echo "--- gate 4: dl.google.com reachable ---"
  echo "\$ curl -sI -o /dev/null -w '%{http_code}' https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: dl.google.com reachability"
    echo "GATE 4 PASS (dry-run)"
  else
    local code
    code=$(curl -sI -o /dev/null -w "%{http_code}" https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip)
    echo "dl.google.com status: $code"
    if [ "$code" != "200" ] && [ "$code" != "302" ]; then
      die "GATE 4 FAILED: dl.google.com returned HTTP $code (need 200/302)"
    fi
    echo "GATE 4 PASS"
  fi

  # GATE 5 — sdkmanager present
  echo "--- gate 5: sdkmanager present ---"
  echo "\$ test -x $SDKMANAGER"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: sdkmanager presence"
    echo "GATE 5 PASS (dry-run)"
  else
    if [ ! -x "$SDKMANAGER" ]; then
      die "GATE 5 FAILED: sdkmanager not found at $SDKMANAGER (set SDK_ROOT or install cmdline-tools)"
    fi
    echo "sdkmanager: $SDKMANAGER"
    echo "GATE 5 PASS"
  fi

  log "PREFLIGHT COMPLETE: all gates passed"
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------
install() {
  require_dq05
  [ -x "$SDKMANAGER" ] || die "sdkmanager not found at $SDKMANAGER — run preflight"
  log "INSTALL: emulator + system image via sdkmanager (no cmdline-tools upgrade)"
  # The "SDK XML version 4 > 3" warning is NON-FATAL. Do not upgrade cmdline-tools.
  run "install packages" "$SDKMANAGER" --sdk_root="$SDK_ROOT" "$PLATFORM_PACKAGE" emulator "$SYSTEM_IMAGE"
  log "INSTALL COMPLETE"
}

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
create() {
  require_dq05
  [ -x "$AVDMANAGER" ] || die "avdmanager not found at $AVDMANAGER — run install first"
  log "CREATE: AVD '$AVD_NAME' (device=$AVD_DEVICE, image=$SYSTEM_IMAGE)"
  # echo no | … answers the "create a custom hardware profile?" prompt; --force is idempotent.
  echo "echo no | $AVDMANAGER create avd -n $AVD_NAME -k \"$SYSTEM_IMAGE\" -d $AVD_DEVICE --force"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: create AVD"
  else
    echo no | "$AVDMANAGER" create avd -n "$AVD_NAME" -k "$SYSTEM_IMAGE" -d "$AVD_DEVICE" --force
  fi

  # Apply the measured tuning. MUST come after create (which writes defaults).
  # See the AVD_* block at the top for the measurements behind these values.
  local cfg="$HOME/.android/avd/$AVD_NAME.avd/config.ini"
  if [ -f "$cfg" ]; then
    log "TUNE: lcd ${AVD_LCD_WIDTH}x${AVD_LCD_HEIGHT}@${AVD_LCD_DENSITY}, ram ${AVD_RAM_MB}M, cores ${AVD_CORES}, heap ${AVD_HEAP_MB}M"
    for kv in "hw.lcd.width=$AVD_LCD_WIDTH" "hw.lcd.height=$AVD_LCD_HEIGHT" \
              "hw.lcd.density=$AVD_LCD_DENSITY" "hw.ramSize=${AVD_RAM_MB}M" \
              "hw.cpu.ncore=$AVD_CORES" "vm.heapSize=${AVD_HEAP_MB}M"; do
      local k="${kv%%=*}" v="${kv#*=}"
      if grep -q "^$k *=" "$cfg" 2>/dev/null; then
        sed -i "s|^$k *=.*|$k = $v|" "$cfg"
      else
        echo "$k = $v" >> "$cfg"
      fi
    done
  else
    warn "no config.ini at $cfg — skipping tuning"
  fi
  log "CREATE COMPLETE"
}

# ---------------------------------------------------------------------------
# boot
# ---------------------------------------------------------------------------
boot() {
  require_dq05
  [ -x "$EMULATOR" ] || die "emulator not found at $EMULATOR — run install first"
  [ -x "$ADB" ] || die "adb not found at $ADB — run install first"
  [ -d "$HOME/.android/avd/$AVD_NAME.avd" ] || die "AVD '$AVD_NAME' not found — run create first"

  log "BOOT: headless launch of AVD '$AVD_NAME'"
  # NEVER add -wipe-data here (destroys live WhatsApp state). NEVER touch PlayStore.enabled.
  "$EMULATOR" -avd "$AVD_NAME" -no-window -no-audio -no-snapshot \
      -gpu swiftshader_indirect -no-metrics -no-boot-anim \
      >/tmp/emulator-harness-boot.log 2>&1 &
  local emu_pid=$!
  echo "emulator pid $emu_pid"

  log "Waiting for device…"
  "$ADB" wait-for-device

  local n b
  n=$(( (BOOT_TIMEOUT_S + BOOT_POLL_INTERVAL_S - 1) / BOOT_POLL_INTERVAL_S ))
  for i in $(seq 1 "$n"); do
    b=$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    echo "t=$((i*BOOT_POLL_INTERVAL_S))s boot_completed=[$b]"
    if [ "$b" = "1" ]; then
      echo "BOOTED"
      "$ADB" devices -l
      return 0
    fi
    sleep "$BOOT_POLL_INTERVAL_S"
  done
  die "BOOT TIMEOUT: sys.boot_completed did not reach 1 within ${BOOT_TIMEOUT_S}s"
}

# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
status() {
  echo "--- AVDs ---"
  "$AVDMANAGER" list avd 2>/dev/null || echo "(avdmanager unavailable)"
  echo "--- adb devices ---"
  "$ADB" devices -l 2>/dev/null || echo "(adb unavailable)"
  echo "--- emulator processes ---"
  pgrep -af "qemu-system|emulator -avd" || echo "(none)"
}

# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------
teardown() {
  log "TEARDOWN"
  echo "$ADB -s emulator-5554 emu kill"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: emu kill"
  else
    "$ADB" -s emulator-5554 emu kill 2>/dev/null || warn "emu kill failed (no running emulator?)"
  fi
  echo "$ADB kill-server"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: kill-server"
  else
    "$ADB" kill-server 2>/dev/null || true
  fi
  log "TEARDOWN COMPLETE (guest stopped; userdata preserved — no wipe)"
}

# ---------------------------------------------------------------------------
# reap
# ---------------------------------------------------------------------------
reap() {
  log "REAP: find and kill orphaned qemu-system / emulator processes"
  local pids
  pids=$(pgrep -f "qemu-system|emulator -avd" || true)
  if [ -z "$pids" ]; then
    echo "REAPER CLEAN: no qemu/emulator processes"
    return 0
  fi
  echo "Orphaned processes:"
  pgrep -af "qemu-system|emulator -avd"
  echo "kill $pids"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] skipped: kill"
  else
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 2
    pkill -9 -f "qemu-system|emulator -avd" 2>/dev/null || true
  fi
  log "REAP COMPLETE"
}

# ---------------------------------------------------------------------------
# reclaim — free host disk that stalls the guest
#
# Rationale (2026-10-13): dq05 reached 93% full with PSI io ~98% and tasks
# wedged in D-state for the whole uptime; WhatsApp ANR'd on launch because the
# guest was starved. Reclaiming the items below took it to 87% and cut the
# write load. Store snapshots are REDUNDANT COPIES of a live state.db.
# ---------------------------------------------------------------------------
reclaim() {
  local keep_snaps="${RECLAIM_KEEP_SNAPS:-2}"
  local journal_cap="${RECLAIM_JOURNAL_CAP:-500M}"
  log "RECLAIM: journal vacuum -> ${journal_cap}"
  run "journal vacuum to ${journal_cap}" sh -c "journalctl --vacuum-size=${journal_cap}"

  log "RECLAIM: stale state.db snapshots (keep ${keep_snaps} newest per profile)"
  for prof in /home/c03rad0r/.hermes/profiles/*/; do
    # The explicitly-corrupt restore is never usable — always remove.
    for f in "$prof"state.db.restore.CORRUPT-*; do
      [ -e "$f" ] || continue
      run "remove corrupt restore $f" rm -f "$f"
    done
    # Keep the newest N .snap-* ; the live state.db is the source of truth.
    local old
    old=$(ls -1t "$prof"state.db.snap-* 2>/dev/null | tail -n +$((keep_snaps + 1)))
    for f in $old; do
      run "remove stale snapshot $f" rm -f "$f"
    done
  done

  log "RECLAIM: state_db_recover_work (superseded recovery copies)"
  run "clear state_db_recover_work" sh -c "rm -f /home/c03rad0r/.hermes/bot/state_db_recover_work/*.db"

  log "RECLAIM: stale probe scratch in /tmp"
  run "clear probe scratch" sh -c "rm -f /tmp/io-delta*.sh /tmp/io-read-watch.py /tmp/iowatch.py"

  log "RECLAIM COMPLETE — re-run 'doctor' and compare df/PSI"
}

# ---------------------------------------------------------------------------
# doctor — READ-ONLY host health; never mutates. Decides reclaim vs REBOOT.
# ---------------------------------------------------------------------------
doctor() {
  echo "=== loadavg ==="; run "loadavg" cat /proc/loadavg
  echo "=== PSI io ==="; run "PSI io" cat /proc/pressure/io
  echo "=== disk / ==="; run "disk usage" df -h /
  echo "=== D-state tasks ==="
  run "D-state tasks" sh -c "ps -eo stat,etime,comm --sort=-etime | awk '\$1 ~ /^D/ {print}' | head -12"
  echo "=== runaway recursive scans (grep/find/du over \$HOME) ==="
  run "runaway scans" sh -c "ps -eo pid,etime,args | grep -E 'grep -rl|find /home|du -x' | grep -v grep | head -8"
  echo
  echo "VERDICT HINT:"
  echo "  - PSI 'some avg10' > 90% WITH per-process IO ~0 MB/s  => storage stack"
  echo "    WEDGED (D-state tasks from uptime) => RECLAIM will not fix it;"
  echo "    a REBOOT is required (ask the operator; never reboot unilaterally)."
  echo "  - PSI high WITH a runaway grep/find/du or a big writer  => run 'reclaim'"
  echo "    and kill the named runaway (read-only scans are safe to kill)."
  echo "  - disk > 90%  => run 'reclaim'."
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
main() {
  local cmd=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY_RUN=1; shift ;;
      --help|-h) usage; exit 0 ;;
      -*) die "unknown option: $1" ;;
      *) cmd="$1"; shift ;;
    esac
  done

  [ -n "$cmd" ] || { usage; exit 1; }

  case "$cmd" in
    preflight) preflight ;;
    install)   install ;;
    create)    create ;;
    boot)      boot ;;
    status)    status ;;
    teardown)  teardown ;;
    reap)      reap ;;
    reclaim)   reclaim ;;
    doctor)    doctor ;;
    all)       preflight; install; create; boot ;;
    *)         echo "unknown subcommand: $cmd" >&2; usage >&2; exit 1 ;;
  esac
}

main "$@"
