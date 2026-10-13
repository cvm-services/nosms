# Why WhatsApp NEXT does not advance on the wa-dev guest — evidence-backed analysis

Task: t_c930a683 (E2 — official WhatsApp APK + JMP-OTP registration)
Branch: `wt/t_c930a683` (pushed to `origin`)
Guest: `wa-dev`, `emulator-5554`, WhatsApp **2.26.39.75**, on dq05 (4 cores)

Status when this was written: **registration NOT complete. No OTP has ever been
requested by any run. Ban risk incurred: zero.** The blocker is the phone-entry
→ verification-screen transition: one NEXT click is delivered and the screen
does not change.

---

## 1. Proven from the captured artifacts (no interpretation)

| # | Fact | Evidence |
|---|------|----------|
| 1 | The APK is installed and the signer was verified in an earlier run | `dumpsys package com.whatsapp` → `versionName=2.26.39.75` + signatures present (manager-verified) |
| 2 | **Text entry works.** The phone field renders `(810) 294-4652` — parentheses and spaces that were never passed in (`set-text` was given the bare `8102944652`) | `10_pre_register.xml`, `11_number_typed.xml`, `12_after_next.xml`, `state.xml` — all `registration_phone` `text="(810) 294-4652"` |
| 3 | WhatsApp's own phone-number formatter ran ⇒ the EditText widget **processed** the input. "The field never received characters" is dead. | same, vs. run-172 dumps `101/102_focus_probe.xml` which show the untouched hint `Phone number` |
| 4 | Exactly **one** `NEXT` node exists: `com.whatsapp:id/button_view`, class `android.widget.Button`, `clickable=true`, `enabled=true`, `bounds=[14,723][346,765]` ⇒ tap centre **(180, 744)**; screen is 360×800 and the nav bar starts at y=779, so the tap point is on-screen and clear of the gesture area | every phone-entry dump |
| 5 | **NEXT was enabled at click time** (`enabled="true"`, green in `40_diag_screen.png`) — a disabled-button no-op is ruled out | `10_pre_register.xml` … `state.xml` |
| 6 | After the click the hierarchy is **the same view set** as before it — same nodes, same bounds, same `enabled`/`focused` — and the screenshot shows plain phone entry: **no dialog, no toast, no spinner, no error** | `12_after_next.xml` vs `10_pre_register.xml`; `40_diag_screen.png` |
| 7 | **No OTP was requested** (inbox `MAX(id)` stayed at 4) ⇒ WhatsApp's submit never reached the "send code" step | `evidence/e2/otp_baseline.txt`; `jmp_inbox.db` |
| 8 | uiautomator2 **3.7.0**'s `UiObject.click()` returns **`None`**: it waits for the node, takes the visible-bounds centre, calls `session.click(x, y)`. There is no success value | `~/wa_u2_venv/.../uiautomator2/_selector.py:138-155` on dq05 |
| 9 | After `press("enter")` the focused node is `com.whatsapp:id/menuitem_overflow`, and the phone EditText is `focused="false"` in **every** dump ⇒ the EditText never held view focus | `next_probe/after_enter.xml`; run-172 `dumpsys input_method` (`mServedView` stuck on `menuitem_overflow`, `mInputShown=false`) |

## 2. Eliminated (do not re-investigate)

- **"Text entry / focus is the blocker."** Eliminated by fact 2+3: the number is
  committed and formatted. (The uiautomator2 `set_text` fix from run-173 is
  correct and stays.)
- **"The wrong node is being clicked / the click misses."** Eliminated by fact 4:
  one NEXT node, centre (180,744), so a coordinate tap and a node tap are the
  same event at the same point.
- **"A refusal/voice-call dialog appeared and was missed."** Eliminated by fact
  6: no dialog node, no error text, and no `VOICE_REFUSAL_MARKERS` hit in the
  post-click dump.
- **"'The click returned success' means it worked."** Eliminated by fact 8: the
  API has no return value; the earlier run's phrase "click returned success" was
  never a signal. Only a screen change is a signal.

## 3. Live hypotheses, ranked, each with its decisive probe

**H1 — guest starvation (most likely).** dq05 is a 4-core box; at the last
attempt it sat at load 9-27 with ~10-15 s guest frame times and a systemui ANR
(manager-measured). A tap that is dispatched but whose handler runs on a starved
main thread looks *exactly* like fact 6 — and the old driver only waited **4 s**.
Probe: `next_stalled_gfxinfo.txt` (janky-frame count, frame durations) and
`next_stalled_logcat.txt` / `next_stalled_activity_anr.txt`. Mitigation already
landed: the post-NEXT wait is now `POST_NEXT_WAIT_S=60` instead of 4.

**H2 — injected input is ignored by the registration screen.** Meta clients are
known to inspect MotionEvent source/flags. Circumstantial support: run-172's
`input tap` moved *window* focus but never transferred *view* focus to a
focusable EditText — abnormal for a genuine tap. Probe: run the three channels
separately on a live guest — (a) `u2 click-text NEXT`, (b) `adb shell input tap
180 744`, (c) an accessibility `ACTION_CLICK` on the node — and diff logcat for
each. The channel that produces a registration-state log line is the one to
keep. Safety bound: each variant is **one** click, and a NEXT that never reaches
submit makes **no** network request ⇒ zero ban surface.

**H3 — no guest egress.** A submit that cannot reach WhatsApp cannot render a
dialog, so it is indistinguishable from a stall. Probe: the new
`guest_egress_ok()` preflight (`ping v.whatsapp.com` + `dumpsys connectivity`
VALIDATED), logged before every NEXT and captured by the `diag` phase.

**H4 — the field must be *focused* (not just set) for WhatsApp's submit
validation.** Note NEXT is `enabled="true"` while the field never had focus, so
enablement is not focus-gated; this is the weakest of the four. Probe:
`dumpsys input_method | grep -E 'mServedView|mInputShown'` after a u2 click on
the field — `mServedView` should be `registration_phone`.

## 4. What changed in the driver for the next pass

`tools/whatsapp/wa_register.py`:

- **NEXT is assert-driven.** One click, then wait (up to 60 s) for a
  verification-screen selector (`POST_NEXT_SELECTORS`). No re-click, ever. A
  click that does not change the screen now fails loud (exit 42) **with the
  diagnostics**, instead of being reported as a tap.
- **New `diag` phase** — read-only, zero ban surface, safe at any load:
  prints egress state + which screen is showing, and writes
  `diag_{logcat,gfxinfo,activity_anr,connectivity}.txt`.
- **Egress preflight** before NEXT (`guest_egress_ok()`), warn-by-default,
  hard-fail under `EGRESS_STRICT=1`.
- **`evidence` phase now states a verdict** — `REGISTERED-STATE CONFIRMED` or
  `NOT registered` — so acceptance criterion 3 cannot be satisfied by a
  screenshot that merely exists.
- The digit guard was lifted into a pure predicate (`phone_field_is_number`) so
  it is covered by the offline test.

`tools/whatsapp/test_wa_register_offline.py` was **rewritten**: it previously
pointed at `~/worktrees/t_c930a683/evidence/ui`, a path from a deleted
workspace, so every case SKIPped and it exited 0 — a false green that validated
nothing. It now asserts against the committed dumps in `evidence/e2/`, including
the run-173 regression itself: **`12_after_next.xml` must be classified as NOT
advanced.** 29/29 checks pass.

## 5. Next worker — do this, in this order

1. `python3 tools/whatsapp/wa_register.py gate` — dq05 1-min load **< 4**.
   Above that, stop: the guest is starved and the pass is uninformative.
2. If the guest is up but the box is busy: `wa_register.py diag` (read-only) and
   read `diag_logcat.txt` / `diag_gfxinfo.txt` — that alone settles H1 vs H2.
3. `bash tools/whatsapp/e2_bringup.sh boot|tunnel` (canonical harness).
4. `wa_register.py state` → `wa_register.py register` → `wa_register.py otp` →
   `wa_register.py evidence`.
5. `bash tools/whatsapp/e2_bringup.sh teardown` — never leave the 3.3 GB guest
   on a 4-core box.
6. If `register` exits 42 with `next_stalled`: **do not re-run it blind.** Read
   the captured logcat/gfxinfo, pick the channel from H2, and only then try
   again.

## 6. Number authority (do not re-litigate)

Live JMP number: **(810) 294-4652** (PORT HURON, MI; JMP bot activation
2026-10-02). `8102583253` was **released** by JMP and is forbidden — typing it
aims a WhatsApp OTP at a stranger. `8102583233` exists only in an older doc and
is forbidden. Both are hard-refused in code and asserted in the offline test.
