# Grafana Certbot Deploy Hook Implementation Plan

> Supporting record in the `grafana-host` Grafana change package.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a domain-scoped Certbot deploy hook that safely refreshes Grafana's copied TLS files and restarts Grafana after successful renewal.

**Architecture:** A root-owned POSIX shell hook receives Certbot's `RENEWED_LINEAGE`, ignores unrelated lineages, validates renewed material in temporary files, and atomically moves valid files into Grafana's certificate directory. It then restarts Grafana and polls the HTTPS health endpoint before reporting success.

**Tech Stack:** Certbot deploy hooks, POSIX shell, OpenSSL, systemd, curl, GNU coreutils

---

## File Structure

- Create: `/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh`
  - Domain filter, secure copy, validation, atomic replacement, restart, and
    health verification.
- Preserve: `/etc/grafana/certs/fullchain.pem`
  - Grafana-readable certificate chain, replaced only after validation.
- Preserve: `/etc/grafana/certs/privkey.pem`
  - Grafana-readable private key, replaced only after validation.

### Task 1: Preflight and failing installation assertion

**Files:**
- Test: `/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh`

- [ ] **Step 1: Confirm required executables and current service health**

Run on `grafana-host` as root:

```bash
command -v install
command -v mktemp
command -v openssl
command -v systemctl
command -v curl
command -v logger
command -v sha256sum
command -v awk
command -v grep
command -v sleep
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health
```

Expected: every `command -v` prints a path, `systemctl` prints `active`, and the
health response contains `"database": "ok"`.

- [ ] **Step 2: Run the pre-install assertion**

```bash
test -x /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
echo "unexpected status=$?"
```

Expected before installation: `unexpected status=1`. If it returns `0`, stop and
inspect the existing hook rather than overwriting it:

```bash
sed -n '1,260p' \
  /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
```

### Task 2: Install the minimal production hook

**Files:**
- Create: `/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh`

- [ ] **Step 1: Ensure the deploy-hook directory exists**

```bash
install -d -o root -g root -m 0755 \
  /etc/letsencrypt/renewal-hooks/deploy
```

Expected: exit status `0`.

- [ ] **Step 2: Install the complete hook with secure ownership and mode**

```bash
install -o root -g root -m 0750 /dev/stdin \
  /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh <<'HOOK'
#!/bin/sh
set -eu

target_lineage=/etc/letsencrypt/live/grafana.example.com
destination_dir=/etc/grafana/certs
certificate_destination=$destination_dir/fullchain.pem
key_destination=$destination_dir/privkey.pem
log_tag=grafana-cert-refresh

log_message() {
    logger -t "$log_tag" -- "$*"
}

if [ "${RENEWED_LINEAGE:-}" != "$target_lineage" ]; then
    log_message "Skipping unrelated lineage: ${RENEWED_LINEAGE:-unset}"
    exit 0
fi

install -d -o root -g grafana -m 0750 "$destination_dir"

certificate_temporary=$(mktemp "$destination_dir/.fullchain.pem.XXXXXX")
key_temporary=$(mktemp "$destination_dir/.privkey.pem.XXXXXX")

cleanup() {
    if [ -n "${certificate_temporary:-}" ]; then
        rm -f -- "$certificate_temporary"
    fi
    if [ -n "${key_temporary:-}" ]; then
        rm -f -- "$key_temporary"
    fi
}
trap cleanup EXIT HUP INT TERM

install -o root -g grafana -m 0640 \
    "$RENEWED_LINEAGE/fullchain.pem" "$certificate_temporary"
install -o root -g grafana -m 0640 \
    "$RENEWED_LINEAGE/privkey.pem" "$key_temporary"

if ! openssl x509 -in "$certificate_temporary" -noout >/dev/null 2>&1; then
    log_message "Certificate validation failed"
    exit 1
fi

if ! openssl pkey -in "$key_temporary" -noout -check >/dev/null 2>&1; then
    log_message "Private-key validation failed"
    exit 1
fi

certificate_public_key=$(
    openssl x509 -in "$certificate_temporary" -pubkey -noout |
        openssl pkey -pubin -outform DER 2>/dev/null |
        sha256sum |
        awk '{print $1}'
)
private_public_key=$(
    openssl pkey -in "$key_temporary" -pubout -outform DER 2>/dev/null |
        sha256sum |
        awk '{print $1}'
)

if [ "$certificate_public_key" != "$private_public_key" ]; then
    log_message "Certificate and private key do not match"
    exit 1
fi

mv -f -- "$certificate_temporary" "$certificate_destination"
certificate_temporary=
mv -f -- "$key_temporary" "$key_destination"
key_temporary=

systemctl restart grafana-server

attempt=0
while [ "$attempt" -lt 30 ]; do
    if systemctl is-active --quiet grafana-server &&
        curl --silent --show-error --fail --insecure --max-time 2 \
            https://127.0.0.1:3000/api/health |
            grep -q '"database": "ok"'; then
        log_message "Grafana certificate refreshed and HTTPS health check passed"
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 1
done

log_message "Grafana did not become healthy within 30 seconds"
exit 1
HOOK
```

Expected: exit status `0`.

- [ ] **Step 3: Validate the installed shell script and metadata**

```bash
/bin/sh -n /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
stat --format='owner=%U group=%G mode=%a' \
  /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
```

Expected:

```text
owner=root group=root mode=750
```

### Task 3: Run the hook and verify the behavior

**Files:**
- Execute: `/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh`
- Verify: `/etc/grafana/certs/fullchain.pem`
- Verify: `/etc/grafana/certs/privkey.pem`

- [ ] **Step 1: Verify an unrelated lineage is ignored**

```bash
before_pid=$(systemctl show grafana-server --property=MainPID --value)
RENEWED_LINEAGE=/etc/letsencrypt/live/unrelated.example \
  /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
after_pid=$(systemctl show grafana-server --property=MainPID --value)
test "$before_pid" = "$after_pid"
echo "unrelated-lineage status=$?"
```

Expected: `unrelated-lineage status=0`; the Grafana PID does not change.

- [ ] **Step 2: Invoke the target-lineage hook**

```bash
RENEWED_LINEAGE=/etc/letsencrypt/live/grafana.example.com \
  /etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
echo "hook status=$?"
```

Expected: `hook status=0`. This intentionally restarts Grafana once.

- [ ] **Step 3: Verify ownership, permissions, service, listener, and health**

```bash
stat --format='%n owner=%U group=%G mode=%a' \
  /etc/grafana/certs/fullchain.pem \
  /etc/grafana/certs/privkey.pem
systemctl is-active grafana-server
ss -ltnp 'sport = :3000'
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health
journalctl -t grafana-cert-refresh -n 10 --no-pager
```

Expected:

- Both files report owner `root`, group `grafana`, and mode `640`.
- `systemctl` reports `active`.
- Grafana owns a listening socket on port 3000.
- Health output contains `"database": "ok"`.
- The journal contains `Grafana certificate refreshed and HTTPS health check passed`.

- [ ] **Step 4: Verify the served and installed certificates match**

```bash
installed_fingerprint=$(
  openssl x509 -in /etc/grafana/certs/fullchain.pem \
    -noout -fingerprint -sha256 |
    cut -d= -f2
)
served_fingerprint=$(
  openssl s_client -connect 127.0.0.1:3000 \
    -servername grafana.example.com </dev/null 2>/dev/null |
    openssl x509 -noout -fingerprint -sha256 |
    cut -d= -f2
)
test "$installed_fingerprint" = "$served_fingerprint"
echo "certificate-match status=$?"
```

Expected: `certificate-match status=0`.

### Task 4: Verify Certbot integration

**Files:**
- Execute: `/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh`

- [ ] **Step 1: Confirm Certbot discovers the deploy hook**

```bash
certbot renew --help all | grep -F -- '--run-deploy-hooks'
```

Expected: help output describing `--run-deploy-hooks`. If this option is absent,
do not pass it in the next command; the manual hook verification in Task 3
already verifies the hook itself.

- [ ] **Step 2: Exercise renewal staging with deploy hooks**

If the previous step found the option:

```bash
certbot renew --dry-run --run-deploy-hooks
```

Otherwise:

```bash
certbot renew --dry-run
```

Expected: Certbot reports a successful simulated renewal. With
`--run-deploy-hooks`, the Grafana hook also logs a successful refresh.

- [ ] **Step 3: Confirm automatic renewal scheduling**

```bash
systemctl list-timers --all | grep -E 'certbot|NEXT|LEFT'
renew_timer=$(
  systemctl list-unit-files --type=timer --no-legend |
    awk '$1 ~ /certbot.*renew\\.timer$/ {print $1; exit}'
)
test -n "$renew_timer"
echo "renew timer=$renew_timer"
systemctl is-enabled "$renew_timer"
systemctl is-active "$renew_timer"
```

Expected: either `certbot.timer` or a package-specific unit such as
`snap.certbot.renew.timer` has a future run time and is both `enabled` and
`active`. If no timer is found because the installation uses cron, inspect it
with:

```bash
grep -R --line-number certbot /etc/cron.d /etc/cron.daily 2>/dev/null
```
