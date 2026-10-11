# REPORT — t_c930a683 (E2: WhatsApp APK + JMP-OTP registration)

Worker: worker-dq05, run 312. Branch `wt/t_c930a683`.
**Outcome: BLOCKED (capacity gate). Registration NOT complete. Zero ban risk taken.**

## What this run did

The card is gated on box load and on a live guest. At run start dq05 was at
1-min load **26.8** (later 20.2) — the harness policy is explicit that a 3.3 GB
guest must not be booted on that 4-core box under load, and the manager's
precondition is "start the registration pass only when dq05 1-min < ~4". The
emulator was **not** booted, no NEXT was clicked, no OTP was requested. Ban risk
incurred by this run: **zero**.

Instead this run did the work that does not need the guest: it root-caused the
`NEXT` non-transition from the captured artifacts and hardened the driver so the
next load window is decisive rather than another silent no-op.

## Deliverables (all committed on `wt/t_c930a683`, pushed)

1. `tools/whatsapp/evidence/e2/NEXT_TRANSITION_ANALYSIS.md` — the analysis.
   Proven facts, eliminated hypotheses, four ranked live hypotheses each with its
   decisive probe, and the next-worker order of operations.
2. `tools/whatsapp/wa_register.py` — hardened:
   - NEXT is **assert-driven**: ONE click, then wait `POST_NEXT_WAIT_S=60` for a
     verification-screen selector; on stall it fails loud (exit 42) **with**
     `next_stalled_logcat.txt` / `_gfxinfo.txt` / `_activity_anr.txt` /
     `_connectivity.txt` captured. It never re-clicks NEXT.
   - new **read-only `diag` phase**: egress + logcat + frame stats + ANR + a
     screen verdict. No taps ⇒ zero ban surface ⇒ safe at any load.
   - guest **egress preflight** before NEXT (warn by default, `EGRESS_STRICT=1`
     to hard-fail).
   - `evidence` phase now prints a `REGISTERED-STATE CONFIRMED` / `NOT registered`
     verdict, so the acceptance criterion cannot be met by a screenshot existing.
   - digit guard lifted into a pure predicate (`phone_field_is_number`).
3. `tools/whatsapp/test_wa_register_offline.py` — **rewritten**. The old version
   pointed at `~/worktrees/t_c930a683/evidence/ui`, a path in a *deleted*
   workspace, so every case printed SKIP and it exited 0 — a false green that
   validated nothing. It now asserts against the committed `evidence/e2/` dumps,
   including the run-173 regression itself (`12_after_next.xml` must classify as
   NOT advanced). **29/29 checks pass.**
4. `PROGRESS.md` — run-312 entry.

## Key findings

- **Text entry works.** The phone field renders `(810) 294-4652` — parentheses and
  spaces never passed in (`set-text` gets the bare `8102944652`), so WhatsApp's
  own formatter ran and the widget processed the input. The run-172 conclusion
  "the EditText never receives characters" is dead.
- **uiautomator2 3.7.0's `UiObject.click()` returns `None`**
  (`_selector.py:138-155` on dq05). It waits for the node, takes the
  visible-bounds centre and injects a tap. There is no success value — the
  earlier phrase "click returned success" was never a signal. Only a screen
  change is.
- **After the NEXT click the hierarchy equals the pre-click hierarchy**, the
  screenshot shows no dialog/spinner/error, and the inbox `MAX(id)` stayed 4 —
  WhatsApp's submit never reached the send-code step.
- Ranked causes: **H1 guest starvation** (the box measured 10-15 s guest frame
  times under load; the old driver waited only 4 s), H2 injected input rejected
  by the registration screen, H3 no guest egress, H4 the field never held focus.

## Verification actually run

- `.venv/bin/python -m pytest -x --tb=short` → **647 passed**, 1 warning
  (Starlette/httpx deprecation), total coverage **87.19%** (gate 80%).
- `python3 tools/whatsapp/test_wa_register_offline.py` → **29/29 checks pass**,
  exit 0.
- `python3 -m py_compile wa_register.py wa_ui.py` → OK.

## Acceptance criteria — honest status

| Criterion | Status |
|---|---|
| APK signer verified as WhatsApp Inc. before install | DONE (earlier run, manager-verified; `versionName=2.26.39.75`, signatures present) |
| `dumpsys package com.whatsapp \| grep versionName` on the emulator | DONE (earlier run) |
| Registration with the JMP number completes; dump shows registered state | **NOT MET** — NEXT never advanced; new `evidence` phase will assert it |
| OTP obtained from the JMP inbox via the documented rails | **NOT MET** — no OTP was ever requested (inbox `MAX(id)` = 4) |
| Halt loudly if WhatsApp demands a voice call / refuses the number | Not triggered: no refusal appeared. Fail-loud halt path is in place and untriggered |
| Evidence committed as a task artifact | DONE for everything this run produced (`evidence/e2/NEXT_TRANSITION_ANALYSIS.md` + the driver/offline-test diffs) |

## Remaining steps (numbered, for the next worker)

1. Wait for dq05 1-min load **< 4** (`ssh dq05 'cat /proc/loadavg'`). Above that,
   stop — the guest is starved and the pass is uninformative.
2. If the guest is already up but the box is busy: run the read-only
   `wa_register.py diag` phase and read `diag_logcat.txt` / `diag_gfxinfo.txt`.
   That alone settles H1 vs H2 without touching registration.
3. `bash tools/whatsapp/e2_bringup.sh boot` and `... tunnel` (canonical harness).
4. `wa_register.py state` → confirm the phone-entry screen.
5. `wa_register.py register` — types the number, logs the egress preflight,
   clicks NEXT **once**, and asserts the verification screen within 60 s.
6. `wa_register.py otp` — polls `jmp_inbox.db` for `id > baseline`, types the
   6-digit code, asserts a registered-state selector.
7. `wa_register.py evidence` — `dumpsys` versionName + screenshot + dump +
   registered verdict.
8. `bash tools/whatsapp/e2_bringup.sh teardown` — never leave the 3.3 GB guest
   on the 4-core box.
9. If `register` exits 42 with `next_stalled`, **do not re-run blind**: read the
   captured logcat/gfxinfo, pick the input channel per hypothesis H2, and retry
   only after that.
