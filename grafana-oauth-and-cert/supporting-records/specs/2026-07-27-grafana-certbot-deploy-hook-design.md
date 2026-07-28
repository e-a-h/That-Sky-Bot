# Grafana Certbot Deploy Hook Design

> Supporting record in the `grafana-host` Grafana change package.

## Objective

Refresh Grafana's copied TLS certificate and private key automatically whenever
Certbot successfully renews the certificate for `grafana.example.com`, then restart
Grafana so the renewed certificate is served immediately.

## Current State

- Grafana serves HTTPS directly on port 3000.
- Grafana reads:
  - `/etc/grafana/certs/fullchain.pem`
  - `/etc/grafana/certs/privkey.pem`
- Direct reads from `/etc/letsencrypt/live/grafana.example.com/` fail for the
  `grafana` user.
- The copied files are readable by Grafana and the service is healthy.

## Selected Approach

Install a root-owned executable deploy hook at:

`/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh`

The hook will:

1. Exit successfully without changing anything unless `RENEWED_LINEAGE` is
   `/etc/letsencrypt/live/grafana.example.com`.
2. Copy `fullchain.pem` and `privkey.pem` from the renewed lineage into temporary
   files in `/etc/grafana/certs`.
3. Set each temporary file to owner `root`, group `grafana`, and mode `0640`.
4. Validate the certificate and private key with OpenSSL.
5. Compare public-key fingerprints to ensure the certificate and key match.
6. Atomically rename the validated temporary files over Grafana's configured
   files.
7. Restart `grafana-server`.
8. Require `grafana-server` to be active and log the result through `logger`.

## Failure Behavior

- A missing source file, failed copy, failed OpenSSL validation, mismatched key,
  failed restart, or inactive service causes a nonzero hook exit.
- Existing Grafana certificate files are not replaced until both temporary files
  pass validation.
- Temporary files are removed on exit.
- The hook never weakens permissions under `/etc/letsencrypt`.

## Verification

Before installing the production hook, execute a test that is expected to fail
because the hook does not yet exist.

After installation:

1. Invoke the hook manually with
   `RENEWED_LINEAGE=/etc/letsencrypt/live/grafana.example.com`.
2. Confirm the hook exits successfully.
3. Confirm `grafana-server` is active.
4. Confirm Grafana is listening with HTTPS on port 3000.
5. Confirm `/api/health` reports `"database": "ok"`.
6. Confirm the served certificate matches the copied certificate.
7. Optionally run `certbot renew --dry-run --run-deploy-hooks` if the installed
   Certbot version supports `--run-deploy-hooks`.

## Operational Notes

- The restart introduces a brief service interruption after a successful
  renewal.
- The hook is domain-scoped so renewal of unrelated certificates does not
  restart Grafana.
- Certbot must already have a scheduled renewal mechanism, such as
  `certbot.timer`.
