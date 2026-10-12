# CVM settlement mint — decision record (2026-10-12)

## Chosen for testing: Amperstrand `micronuts` (local, FakeWallet)

`http://127.0.0.1:3338` — the operator asked specifically for Amperstrand's
signet mint. Its signet mode needs a remote CLN node, so it runs in its
auto-settling FakeWallet mode (unset `MICRONUTS_UPSTREAM_MINT`), which the
upstream AGENTS.md money taxonomy classes as *free rein*.

Brought up by `deploy/micronuts-mint-deploy.sh` (IaC). One systemd user unit,
`micronuts-adapter`, which SPAWNS `mint_server` as its own child — env vars go
on the adapter so the child inherits them. State: `~/.hermes/state/micronuts/`.

**Keyset limit:** micronuts publishes keys only for 1..128 sats. That broke
escrow for every price above 128 until `split_amounts(total, available)` became
mint-aware (commit 00786f5). This is why the fix matters and is not cosmetic.

## Found: we already own a real CDK mint — `https://mint.orangesync.tech`

Live on vps2 (container `cdk-mintd` up 8 days, CDK 0.17.3), deployed by
`wingmen-ops/roles/cdk-mint`. It is a REAL mint on our own domain, not testnut.

- keyset `010fdf6fcea6ec6d…`, denominations 1 .. 2147483648, `input_fee_ppk: 0`
- `[ln] ln_backend = "fakewallet"` per `/opt/cdk-mintd/config.toml.working`
  -> free minting, max_mint 500000 sats
- `mint-auth-processor` container auto-approves quotes
  (`[processor] APPROVED quote=… amount=100`)

### Open issue (NOT a blocker for the test path)
The running container is configured by ENV VARS
(`CDK_MINTD_MNEMONIC`, `CDK_MINTD_URL`, …), and those carry NO `[ln]` section,
so the in-container backend does not see `ln_backend = fakewallet`. A mint quote
created via the HTTP API sat at `UNPAID` for 20 s instead of auto-settling.
Read `/opt/cdk-mintd/config.toml.working` for the intended config; the file is
not what the container reads. Fixing this is a `roles/cdk-mint` change
(pass the LN section through, or mount the config file) and is worth a separate
card — it makes `mint.orangesync.tech` usable as the production mint.

## Recommendation for production
`mint.orangesync.tech` (real, ours, full denominations 1..2^31, 0 fees) once the
env/config gap above is closed. micronuts stays as the second test target --
both are supported now that splitting is mint-aware.
