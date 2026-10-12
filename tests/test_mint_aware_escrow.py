"""Mint-aware splitting: never ask a mint to sign a denomination it has no
keys for.

The Amperstrand `micronuts` mint publishes keys for 1..128 sats only. The
classic power-of-two split of 2900 is [2048, 512, 256,...] — a swap asking for
those fails on the wire with KEYSET_NOT_FOUND, so escrow could never take
payment for a 2900-sat SMS. These tests pin the fix: the split is capped to the
denominations the mint actually published.

`test_the_legacy_split_still_uses_big_denominations` guards the other
direction: with no keyset info we must NOT silently truncate to 128 (that would
turn 2900 sats into 23 outputs and change behaviour for every existing mint).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cashu import split_amounts  # noqa: E402
from app.cvm import ContractContext  # noqa: E402
from app.cvm_tools import CvmTools  # noqa: E402
from app.escrow import EscrowStore  # noqa: E402
from app.transports import FakeTransport  # noqa: E402
from tests.stubs import StubMint, make_token  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[1] / "contract"


def load_docs(contract_dir: Path = CONTRACT) -> dict[str, str]:
    docs: dict[str, str] = {}
    for path in sorted(contract_dir.glob("*.md")):
        docs[path.stem] = path.read_text(encoding="utf-8")
    return docs


def payload(result: dict) -> str:
    return result["content"][0]["text"]


def test_escrow_swap_uses_only_denominations_the_mint_has_keys_for():
    """A 2900-sat payment must escrow against a 128-sat-max keyset."""
    mint = StubMint(max_denomination=128)
    t = CvmTools(
        FakeTransport(), docs=load_docs(CONTRACT),
        owner_pubkeys=set(), mint=mint,
        escrow=EscrowStore(":memory:"),
        contract=ContractContext(npub="npub1testserver",
                                 relays=("wss://relay.test",)),
    )
    # one 2900-sat proof — a naive split would want [2048, 512, 256, 64, 16, 4]
    token = make_token([2900], mint=mint.mint_url, keyset=mint.keyset)
    result = t.call("sms.send", {"to": "+155****4567", "body": "hello",
                                 "cashu_token": token})
    assert "isError" not in result, payload(result)

    outputs = mint.swap_calls[-1]["outputs"]
    assert max(outputs) <= 128, f"asked the mint to sign {max(outputs)}: {outputs}"
    assert sum(outputs) == 2900, f"escrow must hold the full price: {sum(outputs)}"


def test_mint_aware_split_matches_total_exactly():
    """Capped or not, the split must always reconstruct the exact total."""
    for total in (2900, 3072, 768, 64, 1, 129, 255, 2901):
        amounts = split_amounts(total)
        assert sum(amounts) == total, (total, amounts)

        capped = split_amounts(total, [1, 2, 4, 8, 16, 32, 64, 128])
        assert sum(capped) == total, (total, capped)
        assert all(a <= 128 for a in capped), (total, capped)


def test_the_legacy_split_still_uses_big_denominations():
    """No keyset info -> unchanged behaviour (existing mints keep working)."""
    assert split_amounts(2900) == [2048, 512, 256, 64, 16, 4]
    assert split_amounts(64) == [64]
