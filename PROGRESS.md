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
