# PROGRESS — nosms (two workstreams; merged 2026-10-13)

This file carries TWO independent resume maps. Keep both sections when
editing; append to whichever workstream you are on.

---

## A. SMS CVM + public mint

# PROGRESS — SMS CVM end-to-end + public mint (2026-10-12)

## DONE and PUSHED

### nosms (felixfelix-bot/nosms, master)
- 169a935  settlement_receipt bypass CLOSED (SettlementStore, live-refused)
- a4b690f  micronuts IaC bring-up (local)
- 00786f5  mint-aware split_amounts (micronuts keys only go 1..128)
- efdcf4c  live bypass regression probe + this progress map
- 434a396  mint decision record (docs/CVM-MINT-DECISION.md)
- 2a48109  PUBLIC mint on vps2 + CVM repointed to it

### cashu.me PWA (felixfelix-bot/cashu.me, branch wt/cashu-services-ui)
- f624372  pay step wired for real (src/js/cvmPayment.ts + mintPaymentToken)
- 3c0c6f9  vitest hookTimeout fix (337/337 green)
- earlier: 5d53015 3bbf603 808549e fd1f1a1 932d236 72ac566

## PROVEN ON THE WIRE
- bypass: forged settlement_receipt -> bad_settlement (twice, incl. after repoint)
- paid e2e over PUBLIC mint https://mint-test.orangesync.tech:
  snd_15e3366f58ce0214 accepted=true delivery_confirmed=false, escrow 2900 sats
- escrow ledger ALSO shows an earlier paced send as status=failed with
  refunded_at set -> escrow refunding a real failure, unprompted
- browser CORS preflight from the PWA origin: HTTP/2 204 allow-origin *

## PACER — NOT A BUG (was blocking my test, may confuse the next worker)
app/transports/pacing.py draws the next allowed send from the JITTERED window
[NOSMS_JMP_MIN_GAP_SECONDS=60, NOSMS_JMP_MAX_GAP_SECONDS=300]. So "wait 60s" is
wrong — it can be up to 5 minutes. State: ~/.hermes/profiles/manager/state/
jmp_pacing.json (count/20 per day). ADR-0002 personal-line protection.

## MINT FACTS
- mint.orangesync.tech is NOT usable: its log says "Mint info already set, not
  using config file settings" + "melts disabled: private mint has no Lightning
  backend". It ignores its own fakewallet config. Separate card needed.
- mint-test.orangesync.tech = micronuts (rust), keyset 00254ad69403a823,
  keys 1..128 only, input_fee_ppk 0, FakeWallet auto-settle.
- *.orangesync.tech is a DNS wildcard.
- The LIVE Caddy is the HOST systemd unit, /etc/caddy/Caddyfile (pid 780).
  The tollgate-caddy container is stale and NOT running.

## REMAINING
1. build:pwa -> deploy nsite -> restart nsyte-gateway -> operator phone test
2. open the PR for wt/cashu-services-ui
3. optional card: fix cdk-mint env/config gap

---

## B. WhatsApp registration (card t_c930a683)

# PROGRESS — t_c930a683 (nosms WhatsApp E2: APK + JMP OTP registration)

Branch: wt/t_c930a683 (pushed to origin). Worktree: ~/repos/nosms/.worktrees/t_c930a683

## Findings → status → files
- Recovered prior-run assets from ~/worktrees/t_c930a683 (old workspace): wa_ui.py, adb37, ui dumps → committed as tools/whatsapp/wa_ui.py (31fd2b8)
- Number settled per manager comment: (810) 294-4652; 258-3253 RELEASED (forbidden), 258-3233 forbidden → hardcoded refuse-list in wa_register.py
- One-pass registration driver written, fail-loud (exit 42), NO retry: tools/whatsapp/wa_register.py (31fd2b8)
- dq05 load source identified: state_db_autorepair.py --apply (Hermes infra, bounded budget) hammering sda; NOT killed (not ours) → tools/probe_disk_writers.py
- Bring-up wrapper reusing canonical harness over ssh: tools/whatsapp/e2_bringup.sh (dcdd49c)
- adb tunnel 127.0.0.1:15037 -> dq05:5037 UP; JMP listener alive (pid 2731), inbox baseline id=4
- Emulator: DOWN at run start; wa-dev AVD + SDK intact on dq05; WhatsApp 2.26.39.75 installed (manager-verified dumpsys)

## Runbook (the one pass, in order)
1. `python3 tools/whatsapp/wa_register.py gate` — dq05 load < 4 required
2. `bash tools/whatsapp/e2_bringup.sh boot` (canonical harness; ~2-4 min boot)
3. `bash tools/whatsapp/e2_bringup.sh tunnel` (idempotent)
4. `python3 tools/whatsapp/wa_register.py state` — confirm phone-entry screen
5. `python3 tools/whatsapp/wa_register.py register` — types 8102944652, verifies, taps NEXT (STOPS on any voice-call/refusal marker)
6. `python3 tools/whatsapp/wa_register.py otp` — polls jmp_inbox.db id>baseline for 6-digit code, types it
7. `python3 tools/whatsapp/wa_register.py evidence` — dumpsys versionName + screenshot + UI dump
8. `bash tools/whatsapp/e2_bringup.sh teardown` — never leave the 3.3G guest on the 4-core box
9. commit evidence/ + push; kanban_complete (child E3 t_9f3b1c8a released by completion)

- Run 173: uiautomator2 set-text returned and verified live number; follow-up info RPC disconnected, so validation now uses set-text response; NEXT accessibility click returned success but screen stayed on phone-entry and inbox max id remained 4; stopped with zero OTP/ban risk → tools/whatsapp/wa_register.py, tools/whatsapp/evidence/e2/

## STOP conditions (fail-loud, exit 42, never retry)
- voice call demanded / VoIP number refused / "we're unable" / "invalid number" / retry-nudges
- OTP not in inbox within 420s
- phone field shows unexpected digits

## 2026-10-08 14:15 — run 171 outcome: LOAD-GATED, NOT ATTEMPTED
- dq05 never dropped below load ~7 for the whole run (gate needs <4).
- Cause (measured, probe_io_long.py): Hermes state_db repair cycle saturating sda:
  state_db_autorepair.py --apply ran 45min (pid 3288833, ~12MB/s r+w, D-state),
  then state_db_snapshot.py + a SECOND autorepair started (pids 3423901/3396235).
  iostat: sda 76% util, w_await 53-188ms. Not killed — manager-owned infra.
- Per card doctrine the registration pass was NOT attempted (no OTP requested,
  no NEXT tapped; ban risk zero). No retry loop.
- Next worker: when `ssh dq05 'cat /proc/loadavg'` shows 1-min < 4, run the
  runbook above top-to-bottom (~10 min). Everything is committed on
  wt/t_c930a683 (HEAD ba094df) — driver, harness wrapper, offline tests.

## 2026-10-11 22:05 — run 312: LOAD-GATED (dq05 1-min 26.8 → 20.2, gate is 4); NEXT stall root-caused OFFLINE
- Emulator NOT booted (harness policy: no 3.3 GB guest on a 4-core box at load 20+).
  No registration attempted, no NEXT clicked, no OTP requested ⇒ ban risk ZERO.
- Offline root-cause analysis of the NEXT non-transition, written up with evidence:
  tools/whatsapp/evidence/e2/NEXT_TRANSITION_ANALYSIS.md
  * PROVEN: text entry WORKS — the field renders `(810) 294-4652` (WhatsApp's own
    phone formatter ran) while set-text was given the bare `8102944652`; the
    run-172 "field never receives characters" conclusion is dead.
  * PROVEN: uiautomator2 3.7.0's `UiObject.click()` returns **None**
    (`_selector.py:138-155` on dq05) — "the click returned" was NEVER a success
    signal; only a screen change is.
  * PROVEN: post-NEXT hierarchy == pre-NEXT hierarchy; screenshot shows no
    dialog/spinner/error; inbox MAX(id) stayed 4 ⇒ submit never reached WhatsApp.
  * RANKED CAUSES (each with its decisive probe in the artifact):
    H1 guest starvation (that box measured 10-15 s guest frames under load — the
    old driver waited only 4 s), H2 injected input rejected by the registration
    screen, H3 no guest egress, H4 the field never held focus.
- Driver hardened (tools/whatsapp/wa_register.py):
  * NEXT is now ASSERT-DRIVEN: ONE click, then wait POST_NEXT_WAIT_S=60 for a
    verification-screen selector; on stall exit 42 WITH logcat/gfxinfo captured —
    never re-clicked.
  * new read-only `diag` phase: egress + logcat + gfxinfo + ANR + a screen
    verdict. No taps, zero ban surface, safe to run at ANY load.
  * guest egress preflight before NEXT (`guest_egress_ok()`), warn-by-default,
    hard-fail under EGRESS_STRICT=1.
  * `evidence` phase prints a REGISTERED-STATE CONFIRMED / NOT registered verdict.
- Offline test REWRITTEN — it was a FALSE GREEN: it pointed at
  `~/worktrees/t_c930a683/evidence/ui` (a deleted workspace) so every case
  SKIPped and it exited 0. It now asserts against the committed evidence/e2 dumps,
  including the run-173 regression (`12_after_next.xml` must classify as NOT
  advanced): **29/29 checks pass.**

## 2026-10-09 00:15 — run 172 (manager, load window opened): REGISTER BLOCKED — root cause found
- dq05 load 3.67 → GATE PASS. Emulator already up (emulator-5554), WhatsApp 2.26.39.75,
  phone-entry screen confirmed via `state` (US/+1, NEXT present).
- `register` aborts fail-loud at its own focus check (correct: no OTP requested, ban risk ZERO).
- Manual diagnosis (bounded, no retry loop):
  * `input text` AND `input keyevent` digits BOTH drop — field never receives characters.
  * `dumpsys input_method`: mServedView stuck on `menuitem_overflow` (or null), mInputShown=false —
    the IME never starts serving the EditText. Taps land (window focus = RegisterPhone) but
    view focus never transfers.
  * Screenshot shows a green underline on the phone field in EVERY frame including pre-tap —
    that is WhatsApp's static field styling, NOT a focus indicator. The prior "focus probe"
    heuristic (underline = focused) is unreliable; `focused=false` in the dump was right.
- ROOT CAUSE (structural): headless emulator + Gboard → EditText on WhatsApp's registration
  screen does not take view focus from synthetic taps, so no text commits. Known class; the
  standard fixes (pick one on the next pass):
  1. **uiautomator2 (python) driven click + set_text** — accessibility click CAN set focus and
     set_text bypasses the IME entirely. Preferred: no extra APK, same evidence path.
  2. ADBKeyboard IME (broadcast text) — proven for headless WhatsApp automation, but adds an
     APK and still needs focus for field targeting.
- NEXT PASS: rewrite wa_register.py's interaction layer on uiautomator2 (keep the fail-loud
  gates + refuse-lists verbatim), then rerun steps 4-9 of the runbook. Everything else is DONE:
  boot wrapper, tunnel, OTP handoff, inbox baseline (id=4), evidence dir.
bounded NEXT selector and Enter both left WhatsApp on phone-entry screen; no OTP requested -> diagnostic evidence captured -> tools/whatsapp/bounded_next_probe.py, tools/whatsapp/evidence/e2/next_probe/*
