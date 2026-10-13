#!/usr/bin/env python3
"""Offline validation of the wa_register assertions against the REAL UI dumps.

Replays the committed evidence in tools/whatsapp/evidence/e2/ (captured on the
live wa-dev guest) through the same find / refusal / assertion code paths the
live register phase uses. No device, no adb, no network.

Why this file was rewritten: it used to point at
`~/worktrees/t_c930a683/evidence/ui` — a path from a DELETED workspace — so
every case printed SKIP and the script exited 0. That is a false green: it
validated nothing about the driver. This version is path-relative (works from
any checkout) and actually asserts, including the run-173 regression case that
made the driver block: the post-NEXT hierarchy is byte-identical to the
pre-NEXT one, so the new `POST_NEXT_SELECTORS` assertion MUST classify it as
"not advanced" rather than treating the click as progress.

Run:  python3 tools/whatsapp/test_wa_register_offline.py     (exit 0 == all pass)
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wa_register as wr  # noqa: E402
import wa_ui  # noqa: E402

EV = os.path.join(HERE, "evidence", "e2")

# Real dumps from the live guest.
#   10/11/12/state/STOP : run-173 — number typed, NEXT clicked, screen unchanged
#   101/102             : run-172 — field EMPTY (hint shown), NEXT disabled
PHONE_SCREEN_DUMPS = ["10_pre_register.xml", "11_number_typed.xml",
                      "12_after_next.xml", "state.xml", "STOP.xml"]
NUMBER_TYPED_DUMPS = ["10_pre_register.xml", "11_number_typed.xml",
                      "12_after_next.xml", "state.xml"]
EMPTY_FIELD_DUMPS = ["101_focus_probe.xml", "102_focus_probe.xml"]

# Synthetic screens: what the assertions must accept. Shaped like the real
# WhatsApp hierarchy (the verification screen carries the code EditText).
VERIFY_XML = (
    '<hierarchy rotation="0"><node index="0" text="" '
    'resource-id="com.whatsapp:id/verification_code" class="android.widget.EditText" '
    'package="com.whatsapp" focused="false" enabled="true" clickable="true" '
    'bounds="[20,300][340,340]" /></hierarchy>')
REGISTERED_XML = (
    '<hierarchy rotation="0"><node index="0" text="Welcome to WhatsApp" '
    'resource-id="" class="android.widget.TextView" package="com.whatsapp" '
    'focused="false" enabled="true" clickable="false" '
    'bounds="[40,200][320,240]" /></hierarchy>')
# The documented confirm-number dialog: refusal markers must NOT fire on it.
CONFIRM_DIALOG_XML = (
    '<hierarchy rotation="0"><node index="0" text="Is (810) 294-4652 your '
    'number? OK Cancel" resource-id="com.whatsapp:id/message" '
    'class="android.widget.TextView" package="com.whatsapp" focused="false" '
    'enabled="true" clickable="false" bounds="[20,300][340,340]" /></hierarchy>')

_FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  # ' + detail) if detail else ''}")
    if not ok:
        _FAILURES.append(name)


def load(fn: str) -> str:
    path = os.path.join(EV, fn)
    if not os.path.exists(path):
        raise SystemExit(f"MISSING committed evidence: {path}")
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def refusal_markers(xml: str) -> list[str]:
    hay = " ".join(n["text"] + " " + n["content-desc"]
                   for n in wa_ui.nodes(xml) if (n["text"] or n["content-desc"])).lower()
    return [m for m in wr.VOICE_REFUSAL_MARKERS if m in hay]


# --- 1. the phone-entry dumps: field + NEXT present, no refusal, NOT advanced --
# This is the run-173 regression: "NEXT was clicked, screen did not change" must
# be classified as NOT advanced. If this check ever passes-as-advanced, the
# driver would mistake a dropped click for progress again.
for fn in PHONE_SCREEN_DUMPS:
    xml = load(fn)
    phone = wa_ui.find(xml, rid=wr.PHONE_SCREEN_RID)
    nxt = wa_ui.find(xml, text="NEXT", exact=True)
    advanced = wr.match_any(xml, wr.POST_NEXT_SELECTORS)
    registered = wr.match_any(xml, wr.REGISTERED_SELECTORS)
    check(f"{fn}: phone-entry field + NEXT present",
          phone is not None and nxt is not None,
          f"phone={phone is not None} next={nxt is not None}")
    check(f"{fn}: no refusal marker fired", not refusal_markers(xml),
          f"markers={refusal_markers(xml)}")
    check(f"{fn}: classified NOT advanced (post-NEXT selector absent)",
          advanced is None and registered is None)

# --- 2. digit guard: the rendered value is what the driver must compare -------
for fn in NUMBER_TYPED_DUMPS:
    xml = load(fn)
    phone = wa_ui.find(xml, rid=wr.PHONE_SCREEN_RID)
    rendered = phone["text"] if phone else ""
    check(f"{fn}: field renders a value the digit guard accepts",
          wr.phone_field_is_number(rendered),
          f"rendered={rendered!r} digits={wr.field_digits(rendered)!r}")

for fn in EMPTY_FIELD_DUMPS:
    xml = load(fn)
    phone = wa_ui.find(xml, rid=wr.PHONE_SCREEN_RID)
    rendered = phone["text"] if phone else ""
    check(f"{fn}: EMPTY field rejected by the digit guard (abort before NEXT)",
          phone is not None and not wr.phone_field_is_number(rendered),
          f"rendered={rendered!r}")
    # and the disabled NEXT must not be clickable-attempted: enabled=false
    nxt = wa_ui.find(xml, text="NEXT", exact=True)
    check(f"{fn}: NEXT is disabled on the empty field",
          nxt is not None and nxt["enabled"] == "false",
          f"enabled={nxt['enabled'] if nxt else None}")

# --- 3. the assertions must FIRE on the screens they exist for ----------------
check("verify screen accepted by POST_NEXT_SELECTORS",
      wr.match_any(VERIFY_XML, wr.POST_NEXT_SELECTORS) is not None)
check("registered screen accepted by REGISTERED_SELECTORS",
      wr.match_any(REGISTERED_XML, wr.REGISTERED_SELECTORS) is not None)
check("confirm-number dialog raises NO refusal marker (it is the documented path)",
      not refusal_markers(CONFIRM_DIALOG_XML))
check("no cross-talk: verify selector absent from a registered screen",
      wr.match_any(REGISTERED_XML, wr.POST_NEXT_SELECTORS) is None)

# --- 4. click target: the injected tap must land on the NEXT button -----------
check("NEXT bounds centre is the seeded tap point (180,744)",
      wa_ui.center(wa_ui.find(load("10_pre_register.xml"), text="NEXT",
                              exact=True)["bounds"]) == (180, 744))

# --- 5. the number guard: the released/older numbers must stay refused ---------
check("live JMP number is not in the forbidden set",
      wr.JMP_NUMBER not in wr.FORBIDDEN, wr.JMP_NUMBER)
check("released (810) 258-3253 stays forbidden", "8102583253" in wr.FORBIDDEN)
check("older-doc (810) 258-3233 stays forbidden", "8102583233" in wr.FORBIDDEN)

print()
if _FAILURES:
    print(f"FAILED {len(_FAILURES)} check(s): {_FAILURES}")
    sys.exit(1)
print("ALL OFFLINE CHECKS PASSED")
sys.exit(0)
