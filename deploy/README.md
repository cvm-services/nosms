# Deploying the nosms ContextVM service

The service is a long-lived Nostr client: it publishes the CEP-6 catalogue
(kinds 11316/11317/11318) on the CVM relays and then answers gift-wrapped
`tools/call` requests. It is **not** an HTTP service — the HTTPS host is only
used for the human-readable contract. So it must run somewhere that stays up.

## systemd (user unit) — the live deployment

    install -Dm644 deploy/systemd/nosms-cvm-server.service \
        ~/.config/systemd/user/nosms-cvm-server.service
    systemctl --user daemon-reload
    systemctl --user enable --now nosms-cvm-server.service
    journalctl --user -u nosms-cvm-server.service -f

`deploy/systemd/nosms-cvm-server.service` is the exact unit running on
CobradorWave, copied from `~/.config/systemd/user/`. It runs the **repo clone on
master** (not a worktree, so worktree pruning cannot kill the service) and pins:

- `NOSMS_TRANSPORT=jmp` — the rail must be started by the serving process
  (`transport.start()` before the announcement + listen loop, PR #12). Without
  it `sms.send` answers `rail_not_configured` forever.
- `NOSMS_JMP_RESOURCE=cvmsvc` — a distinct XMPP resource so the service never
  fights the operator's own listener session on the same JID.
- the relay set **including `wss://relay.primal.net`** — mandatory, see below.
- `NOSMS_DB_PATH` under `~/.hermes/state/`, so the escrow DB is not in the tree.

The server key file is `~/.repos/nosms/.cvm-server.nsec` (0600, gitignored), so
restarts keep the same service npub.

## Known live defect: the contextvm relays drop gift-wrapped replies

Measured 2026-10-11/12 on the running service:

    [nosms-cvm] replied -> success=[primal]
      failed={ relay2.contextvm.org: 'invalid: event expired',
               relay.contextvm.org:  'invalid: event expired' }

NIP-59 requires gift wraps to backdate `created_at` up to 2 days; strfry (both
CVM relays) is configured with a max event age, so any wrap older than that
window is rejected — the announcement is accepted by all three relays, later
replies are not. A client that reads only the two CVM relays sees no answer
roughly half the time. Mitigation (in force): keep `relay.primal.net` in both
the service and the client relay sets. The real fix is tracked separately.
