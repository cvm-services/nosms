# Phone-assisted WhatsApp registration — runbook

**Status:** ready · **Last verified:** 2026-10-13 · **Owner:** Felix / fleet

## Why this runbook exists

WhatsApp's registration submit **silently refuses to run on an emulator**
(measured 2026-10-13: every UI interaction works on our headless rail at
540×1200 — EULA, language, text entry, button arm/disarm — but the NEXT
submit no-ops via every input path, with **zero connections to Meta servers**
while every other step functions). Registration is the *only* emulator-hostile
step. **Linked-companion messaging is a normal, supported flow.**

So: register **once on a real phone** (a friend's test phone), then link our
emulator as a companion device. From then on all sending is programmatic on
the emulator rail (`nosms` repo, fully IaC'd).

- **The friend's phone keeps nothing.** The account is keyed to Felix's JMP
  number (810-294-4652); the friend's handset is only the registration vehicle.
- **The OTP arrives on OUR side** (JMP gateway → `jmp_inbox.db` on cobrador),
  so we hand the friend the code — he never sees a secret he has to keep.

## What each side needs

| Side | Needs | Time |
|---|---|---|
| Friend | any Android phone, WhatsApp installed, 5 min | ~5 min |
| Us | cobrador (OTP poll), dq05 emulator up (QR link) | ~10 min |

## Part 1 — Friend's steps (registration)

> He does this while we run the OTP poll (Part 2) in parallel.

1. Install WhatsApp from the Play Store (skip if present).
2. Open WhatsApp, **Agree and continue**.
3. Country: **United States** (+1). Phone number: **810 294 4652**.
4. Tap **Next**, confirm the number.
5. WhatsApp says it will text a code — **wait**. We read it out to him
   (it lands in our JMP inbox within seconds).
6. Enter the 6-digit code we give him.
7. **Skip / deny everything optional:** contacts sync (*Not now*), backup
   restore, notifications. The account has no history — keep it empty.
8. Done — the account now exists, keyed to the JMP number.

**If WhatsApp offers "register without SMS" / a voice call instead:** fine,
either works; the code still lands on our side for SMS. For voice we cannot
read it — in that case he types what he hears.

## Part 2 — Our steps (read the OTP, hand it over)

On **cobrador**:

```bash
cd ~/repos/nosms
# 1. current baseline BEFORE the friend taps Next
python3 tools/whatsapp/wa_otp_poll.py --print-baseline
#    -> e.g. 14

# 2. poll for the code (run this, THEN have the friend tap Next)
python3 tools/whatsapp/wa_otp_poll.py --baseline 14 --timeout 300
#    -> prints the 6-digit code on stdout when the SMS lands
```

Then message the friend the code (Signal/WhatsApp to his own number).

## Part 3 — Link the emulator as a companion (QR)

Prereq: emulator up on dq05 (`ssh dq05 'bash ~/emulator-harness.sh boot'`,
then wait for `sys.boot_completed=1`).

On **cobrador**:

```bash
cd ~/repos/nosms
bash tools/whatsapp/wa_qr_capture.sh     # -> ~/wa-link-qr-<ts>.png
```

Send the PNG to the friend → on the registered phone:
**WhatsApp → Settings → Linked devices → Link a device → scan**.

The emulator's WhatsApp session activates as a companion. Verify on dq05:

```bash
adb shell dumpsys window | grep mCurrentFocus
# HomeActivity (chat list) = linked and live
```

## Part 4 — Hand the friend's phone back

Nothing to clean: he typed a code and scanned a QR. His phone now shows the
account in its WhatsApp app — **have him log out / delete the app data** if he
doesn't want it there:

> WhatsApp → Settings → Linked devices → *(this device)* → Log out
> (or just uninstall; the account survives on our companion.)

Optional but recommended: he can also delete the WhatsApp account from his
handset entirely; the companion link is independent.

## Afterword — what lives where (IaC map)

- `tools/whatsapp/wa_otp_poll.py` — OTP poll against `jmp_inbox.db`
  (`JMP_INBOX_DB` overridable; read-only URI; prints the code on stdout)
- `tools/whatsapp/wa_qr_capture.sh` — screencap the link-QR off the emulator
- `tools/emulator/emulator-harness.sh` — boot/teardown/doctor/reclaim +
  `AVD_*` tuning knobs (540×1200, 4G, 4 cores — the dropped-click fix)
- `roles/92-adb-tunnel` (hermes-orchestration) — durable adb tunnel units
- skill `android-emulator-rail` — the full pitfall catalogue (IME/focus bug,
  framebuffer fix, IPv6 adb trap, reboot-wipes-/tmp, emulator detection)

## Caveats (honest)

- **Primary-phone offline > ~14 days** drops linked devices. The friend's
  phone is only the registration vehicle — but if it is wiped immediately, the
  account has no primary. **Plan: after linking, ALSO install WhatsApp on a
  device we control as a second companion** (or keep the emulator as the sole
  survivor and accept re-registration every ~2 weeks is NOT how it works —
  companions need *a* primary that comes online occasionally). Simplest
  durable setup: link the emulator AND keep one cheap physical Android at
  home as the primary.
- The registration is real: the JMP number becomes a WhatsApp account.
  Bans would hit the number, so keep the account boring (no bulk sending)
  until the rail has sent some normal-looking traffic.
- If registration ever needs redoing, repeat this runbook — the tooling is
  unchanged.
