# PROGRESS — nosms CVM: settlement verifier + micronuts mint

## Landed and pushed (felixfelix-bot/nosms, master)
- 169a935  fix(security): verify CEP-8 settlement receipts for real (bypass closed)
- a4b690f  feat(deploy): IaC bring-up for the Amperstrand micronuts mint
- 00786f5  fix(escrow): split into the denominations the mint actually has keys for

## Live-proven
- bypass CLOSED: fabricated settlement_receipt="rcpt-attack" -> bad_settlement
  (scripts/probe_bypass_live.py, run twice: pre- and post-mint-repoint)
- PAID E2E: cvm_live_verify.py --mint http://127.0.0.1:3338 --to +18102940908
  -> accepted=True, id snd_bef35f0fc8ed3598, 2900 sats escrowed, change 1024
  -> escrows table row confirmed (message_id/price/change/escrow_token/change_token)
- mint: micronuts at http://127.0.0.1:3338, keyset 009a792fd2691c57, keys 1..128
  unit micronuts-adapter (spawns mint_server as child), state ~/.hermes/state/micronuts/

## Remaining (next)
1. App pay step in ServicesPage.vue — wire the CVM call (cashu_token path ready).
   Token must be minted at the SAME mint URL the CVM escrows against (string
   compare in cvm_tools.py:240 -> token_wrong_mint otherwise).
2. Public URL for the mint (vps2 Caddy) so the PWA can mint from the browser,
   then repoint NOSMS_MINT_URL to that URL in IaC.
3. Build + deploy nsite + restart nsyte-gateway on vps2.
4. Operator phone test; done only when the operator confirms usable in the PWA.
5. Open PR for wt/cashu-services-ui (not yet opened).
6. settlement_receipt ISSUANCE tool — the store verifies receipts but nothing
   issues them yet. Needed only for the bolt11/settlement path in the app.
