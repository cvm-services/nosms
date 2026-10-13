#!/usr/bin/env python3
"""Poll the JMP inbox for a WhatsApp verification code.

The JMP (jmp.chat / Cheogram) number receives the SMS; the gateway mirrors it
into a local SQLite inbox. This is the OPERATOR-SIDE half of the phone-assisted
registration runbook: the friend's phone triggers the OTP, we read it here and
hand the friend the digits.

Usage:
  wa_otp_poll.py --baseline            print the current MAX(id) and exit
  wa_otp_poll.py [--baseline N]        poll for the first inbound SMS with id>N
  wa_otp_poll.py --timeout 300         bound the wait (default 300s)

Env:
  JMP_INBOX_DB   path to the inbox (default matches the driver's default)

Exit 0 with the code on stdout when found; exit 2 on timeout; exit 1 on error.
Prints progress to stderr so stdout stays machine-readable.
"""
import argparse
import os
import re
import sqlite3
import sys
import time

DEFAULT_DB = os.path.expanduser(
    os.environ.get("JMP_INBOX_DB",
                   "~/.hermes/profiles/manager/state/jmp_inbox.db"))

# WhatsApp codes are 3-6 digits, often "NNN-NNN" or with a "code is" preamble.
CODE_RE = re.compile(r"(?<!\d)(\d{3})[-\s]?(\d{3})(?!\d)")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def connect(db):
    # read-only URI so a crashed poll can never lock the writer
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)


def max_id(db):
    with connect(db) as c:
        row = c.execute("SELECT MAX(id) FROM messages").fetchone()
    return row[0] if row and row[0] is not None else 0


def fetch_new(db, baseline):
    """Newest inbound SMS with id > baseline, or None."""
    with connect(db) as c:
        row = c.execute(
            "SELECT id, body FROM messages "
            "WHERE id > ? AND direction = 'inbound' "
            "ORDER BY id ASC LIMIT 1", (baseline,)).fetchone()
    return row


def extract_code(body):
    if not body:
        return None
    m = CODE_RE.search(body)
    if m:
        return m.group(1) + m.group(2)
    # fall back to any 4-6 digit run
    m = re.search(r"(?<!\d)(\d{4,6})(?!\d)", body)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--baseline", type=int, default=None,
                    help="poll for id > N (omit to auto-read current MAX)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--print-baseline", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        log(f"FATAL: inbox not found: {args.db}")
        log("       set JMP_INBOX_DB or pass --db")
        return 1

    try:
        base = args.baseline if args.baseline is not None else max_id(args.db)
    except sqlite3.Error as e:
        log(f"FATAL: cannot read {args.db}: {e}")
        return 1

    if args.print_baseline:
        print(base)
        return 0

    log(f"baseline id={base}; waiting up to {args.timeout}s for a new inbound SMS")
    deadline = time.time() + args.timeout
    seen_deadline_warned = False
    while time.time() < deadline:
        try:
            row = fetch_new(args.db, base)
        except sqlite3.Error as e:
            # a transient DB error must not abort the wait
            log(f"warn: {e}")
            row = None
        if row:
            mid, body = row
            code = extract_code(body)
            log(f"new SMS id={mid}: {body[:80]!r}")
            if code:
                print(code)
                return 0
            log("no code pattern in that SMS; continuing")
            base = mid
        else:
            left = int(deadline - time.time())
            if left <= 30 and not seen_deadline_warned:
                log(f"still waiting ({left}s left)")
                seen_deadline_warned = True
        time.sleep(args.interval)

    log(f"TIMEOUT after {args.timeout}s — no new inbound SMS with a code")
    return 2


if __name__ == "__main__":
    sys.exit(main())
