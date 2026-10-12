"""LIVE regression probe: a fabricated settlement_receipt must still be refused.

Sends `sms.send(settlement_receipt="rcpt-attack")` — the exact payload the
pre-169a935 code honoured — and prints the reply. Expects an error with
reason=bad_settlement. Touches no SMS: the refusal happens before the rail.
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, "/home/c03rad0r/repos/nosms")

from nostr_sdk import (ClientBuilder, EventBuilder, Filter, Keys, Kind,
                       NostrSigner, PublicKey, RelayUrl, Tag)

SERVER_NPUB = "npub1yfd2zvsq3lmz7n6ckjt77rm0a56s3d49n2xvpc0ct2tzx24c4wuqn4h6hf"
RELAYS = ["wss://relay.contextvm.org", "wss://relay2.contextvm.org",
          "wss://relay.primal.net"]


async def main() -> int:
    keys = Keys.parse(open("/home/c03rad0r/repos/nosms/.cvm-client.nsec").read().strip())
    client = ClientBuilder().signer(NostrSigner.keys(keys)).build()
    for url in RELAYS:
        await client.add_relay(RelayUrl.parse(url))
    await client.connect()
    await asyncio.sleep(1.0)
    server_pk = PublicKey.parse(SERVER_NPUB)
    replies: dict[str, tuple] = {}

    class Handler:
        async def handle_msg(self, relay_url, msg):
            pass

        async def handle(self, relay_url, subscription_id, event):
            try:
                if event.kind().as_u16() not in (1059, 21059):
                    return
                p = None
                for tag in event.tags().to_vec():
                    vals = tag.as_vec()
                    if vals and vals[0] == "p":
                        p = vals[1]
                        break
                if p != keys.public_key().to_hex():
                    return
                unwrapped = await client.unwrap_gift_wrap(event)
                rumor = unwrapped.rumor()
                if rumor.kind().as_u16() != 25910:
                    return
                message = json.loads(rumor.content())
            except Exception:
                return
            replies[str(message.get("id"))] = (time.time(), message)

    asyncio.get_running_loop().create_task(client.handle_notifications(Handler()))
    await client.subscribe(Filter().kinds([Kind(1059), Kind(21059)]))
    await asyncio.sleep(2.0)

    call_id = "bypass-live-1"
    request = {"jsonrpc": "2.0", "id": call_id, "method": "tools/call",
               "params": {"name": "sms.send",
                          "arguments": {"to": "+18102940908", "body": "bypass probe",
                                        "settlement_receipt": "rcpt-attack"}}}
    rumor = EventBuilder(Kind(25910), json.dumps(request)).tags(
        [Tag.public_key(server_pk)]).build(keys.public_key())
    print("sending fabricated settlement_receipt='rcpt-attack' ...")
    await client.gift_wrap(server_pk, rumor, [])

    got = None
    started = time.time()
    while time.time() - started < 45:
        if call_id in replies:
            got = replies[call_id][1]
            break
        await asyncio.sleep(0.5)
    await client.shutdown()

    if not got:
        print("NO REPLY CAPTURED within 45s (check server log)")
        return 2
    print("REPLY:", json.dumps(got, indent=2)[:800])
    verdict = "CLOSED" if "bad_settlement" in json.dumps(got) else "STILL OPEN?"
    print("VERDICT:", verdict)
    return 0 if verdict == "CLOSED" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
