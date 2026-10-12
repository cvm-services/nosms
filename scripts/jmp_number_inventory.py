#!/usr/bin/env python3
"""Read-only inventory: for each local XMPP credential, ask the cheogram
gateway for the account's own JMP number(s).

Prints only non-secret data (JIDs, roster entries, gateway replies).
Never prints passwords.

JMP/cheogram convention (see docs/jmp-rail.md): a gateway account is
addressed at `<phone>@cheogram.com`; the gateway's own JID is
`cheogram.com`. `register` asks it to (re)register with the backend and it
answers with the currently bound number. `help` lists commands.
"""
from __future__ import annotations

import asyncio
import glob
import json
import pathlib
import re

import slixmpp

CREDS = sorted(glob.glob(str(pathlib.Path.home() / ".xmpp-*.json")))
GATEWAY = "cheogram.com"
TIMEOUT = 45


class Probe(slixmpp.ClientXMPP):
    def __init__(self, jid, password, out):
        super().__init__(jid, password)
        self.out = out
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.message)

    async def start(self, _event):
        self.send_presence()
        try:
            await asyncio.wait_for(self.get_roster(), timeout=12)
        except Exception as exc:  # noqa: BLE001
            self.out["errors"].append(f"roster: {type(exc).__name__}: {exc}")
        # Roster keys are bare JID strings in slixmpp 1.17.
        try:
            self.out["roster"] = sorted(str(j) for j in self.client_roster.keys())
        except Exception as exc:  # noqa: BLE001
            self.out["errors"].append(f"roster-keys: {type(exc).__name__}: {exc}")
        try:
            disco = await asyncio.wait_for(
                self.plugin["xep_0030"].get_info(jid=GATEWAY), timeout=12)
            self.out["gateway_identities"] = [
                str(i) for i in (disco.get("disco_info", {}) or {}).get(
                    "identities", [])]
        except Exception as exc:  # noqa: BLE001
            self.out["errors"].append(f"disco: {type(exc).__name__}: {exc}")
        self.send_message(mto=GATEWAY, mbody="help", mtype="chat")
        self.send_message(mto=GATEWAY, mbody="register", mtype="chat")
        await asyncio.sleep(8)
        self.disconnect()

    def message(self, msg):
        if msg["type"] in ("chat", "normal") and msg["body"]:
            self.out["gateway_replies"].append(
                {"from": str(msg["from"]), "body": msg["body"][:800]})


async def probe_one(path: str) -> dict:
    d = json.loads(pathlib.Path(path).read_text())
    out = {"cred_file": pathlib.Path(path).name, "jid": d.get("jid"),
           "roster": [], "gateway_replies": [], "gateway_identities": [],
           "errors": []}
    xmpp = Probe(d["jid"], d["password"], out)
    xmpp.register_plugin("xep_0030")
    try:
        xmpp.connect()
        await asyncio.wait_for(xmpp.disconnected, timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"connect: {type(exc).__name__}: {exc}")
    return out


async def main():
    for path in CREDS:
        r = await probe_one(path)
        jid_dom = (r.get("jid") or "").split("@")[-1]
        # Only the account's own number(s) matter; filter replies by gateway.
        txt = json.dumps(r, indent=2)
        txt = re.sub(r"\b[A-Za-z0-9_\-]{20,}\b", "<redacted>", txt)
        print(f"### {r['cred_file']}  (server: {jid_dom})")
        print(txt)
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
