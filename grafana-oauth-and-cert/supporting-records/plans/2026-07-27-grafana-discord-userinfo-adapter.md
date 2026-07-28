# Grafana Discord UserInfo Adapter Implementation Plan

> Supporting record in the `grafana-host` Grafana change package.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a loopback-only Discord UserInfo adapter that supplies a stable OpenID `sub`, migrate the one existing blank Grafana OAuth identity, and preserve Discord role-based Viewer/server-admin authorization.

**Architecture:** Grafana sends its UserInfo request to a dependency-free Python service on `127.0.0.1:9080`. The service forwards the bearer token to Discord `/users/@me`, validates the response, and returns it with `sub` copied from Discord's stable `id`; Grafana continues calling Discord's guild-member endpoint directly for role admission.

**Tech Stack:** Python 3.6.9 standard library, `unittest`, systemd, Grafana 13.1.1 Generic OAuth, Discord OAuth2 API v10, SQLite 3.22.

---

## File Map

- Create `/usr/local/lib/grafana-discord-userinfo/adapter.py`
  - Loopback HTTP server, Discord UserInfo fetch, validation, and `sub`
    normalization.
- Create `/usr/local/lib/grafana-discord-userinfo/test_adapter.py`
  - Standard-library unit and local HTTP tests; no live Discord calls.
- Create `/etc/systemd/system/grafana-discord-userinfo.service`
  - Dedicated unprivileged service with restart and hardening settings.
- Modify Grafana's database-backed Generic OAuth settings through
  **Administration → Authentication → Generic OAuth**
  - Change only `api_url` to the loopback adapter.
- Modify `/var/lib/grafana/grafana.db`
  - After stopping Grafana and taking a verified backup, replace the user
    identified by `GRAFANA_USER_ID` and its empty
    `oauth_generic_oauth.auth_id` with Discord ID `DISCORD_ADMIN_USER_ID`.
- Modify `/etc/grafana/grafana.ini`
  - Merge `oauth.generic_oauth:error` into `[log] filters` after functional
    verification so Grafana stops journaling opaque Discord bearer tokens.

The remote host configuration is not Git-managed. Use the verified database
backup, exact file copies, unit tests, and checksums as the rollback/audit trail
instead of commits.

### Task 1: Preflight and Recoverable Database Backup

- [ ] **Step 1: Verify required tools and preserve recovery access**

Keep one working local Grafana administrator browser session open and keep the
root shell open.

Run:

```bash
python3 --version
sqlite3 --version
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health | jq '{database,version}'
```

Expected:

- Python 3 is installed.
- SQLite is installed.
- Grafana is `active`.
- Health reports `"database": "ok"`.

- [ ] **Step 2: Verify the affected identity has not changed**

Run:

```bash
sqlite3 -header -column /var/lib/grafana/grafana.db "
SELECT
  ua.user_id,
  u.login,
  quote(ua.auth_id) AS auth_id,
  length(ua.auth_id) AS auth_id_length
FROM user_auth AS ua
JOIN user AS u ON u.id = ua.user_id
WHERE ua.auth_module = 'oauth_generic_oauth';
"
```

Expected exactly one row:

```text
GRAFANA_USER_ID  grafana-admin-user  ''  0
```

Stop if additional OAuth rows exist or the user identified by
`GRAFANA_USER_ID` no longer has an empty
`auth_id`; revise the migration scope before continuing.

- [ ] **Step 3: Stop Grafana and create a verified backup**

Run:

```bash
test ! -e /var/lib/grafana/grafana.db.pre-discord-sub
systemctl stop grafana-server
sqlite3 /var/lib/grafana/grafana.db \
  ".backup '/var/lib/grafana/grafana.db.pre-discord-sub'"
chown root:grafana /var/lib/grafana/grafana.db.pre-discord-sub
chmod 0640 /var/lib/grafana/grafana.db.pre-discord-sub
sqlite3 /var/lib/grafana/grafana.db.pre-discord-sub \
  'PRAGMA integrity_check;'
sha256sum /var/lib/grafana/grafana.db.pre-discord-sub
systemctl start grafana-server
```

Expected:

- `PRAGMA integrity_check` prints `ok`.
- `sha256sum` prints and records one checksum.
- If the fixed backup path already exists, the first command fails before
  stopping Grafana; do not overwrite the existing backup.

- [ ] **Step 4: Verify recovery startup**

Run:

```bash
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health | jq '{database,version}'
```

Expected: Grafana is `active` and the database is `ok`.

### Task 2: Build the Adapter Test-First

- [ ] **Step 1: Create the application directory**

Run:

```bash
install -d -o root -g root -m 0755 \
  /usr/local/lib/grafana-discord-userinfo
```

- [ ] **Step 2: Write the failing tests**

Create `/usr/local/lib/grafana-discord-userinfo/test_adapter.py` with:

```python
#!/usr/bin/python3
import http.client
import json
import threading
import unittest

from adapter import (
    AdapterError,
    ThreadingHTTPServer,
    UserInfoHandler,
    normalize_discord_user,
)


VALID_USER = {
    "id": "DISCORD_ADMIN_USER_ID",
    "username": "grafana-admin-user",
    "email": "user@example.invalid",
    "verified": True,
}


class NormalizeTests(unittest.TestCase):
    def test_adds_sub_from_discord_id(self):
        result = normalize_discord_user(VALID_USER)
        self.assertEqual(result["sub"], VALID_USER["id"])
        self.assertEqual(result["id"], VALID_USER["id"])
        self.assertEqual(result["username"], VALID_USER["username"])

    def test_overwrites_untrusted_sub(self):
        payload = dict(VALID_USER, sub="wrong")
        result = normalize_discord_user(payload)
        self.assertEqual(result["sub"], VALID_USER["id"])

    def test_rejects_missing_required_field(self):
        for field in ("id", "username", "email"):
            with self.subTest(field=field):
                payload = dict(VALID_USER)
                payload.pop(field)
                with self.assertRaises(AdapterError):
                    normalize_discord_user(payload)

    def test_rejects_unverified_email(self):
        with self.assertRaises(AdapterError):
            normalize_discord_user(dict(VALID_USER, verified=False))

    def test_rejects_non_object(self):
        with self.assertRaises(AdapterError):
            normalize_discord_user([])


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.seen_authorization = []
        seen = self.seen_authorization

        class TestHandler(UserInfoHandler):
            fetcher = staticmethod(
                lambda authorization: (
                    seen.append(authorization)
                    or normalize_discord_user(VALID_USER)
                )
            )

        self.handler_class = TestHandler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def request(self, method="GET", path="/userinfo", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_port,
            timeout=2,
        )
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, response.getheaders(), body

    def test_success_returns_normalized_profile(self):
        status, headers, body = self.request(
            headers={"Authorization": "Bearer test-token"}
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["sub"], VALID_USER["id"])
        self.assertEqual(payload["id"], VALID_USER["id"])
        self.assertEqual(
            self.seen_authorization,
            ["Bearer test-token"],
        )
        self.assertIn(("Cache-Control", "no-store"), headers)

    def test_missing_authorization_is_rejected(self):
        status, _, body = self.request()
        self.assertEqual(status, 401)
        self.assertEqual(
            json.loads(body)["error"],
            "missing_bearer_token",
        )
        self.assertEqual(self.seen_authorization, [])

    def test_wrong_path_is_rejected(self):
        status, _, _ = self.request(
            path="/other",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.seen_authorization, [])

    def test_non_get_method_is_rejected(self):
        status, _, _ = self.request(
            method="POST",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 405)
        self.assertEqual(self.seen_authorization, [])

    def test_upstream_failure_is_fail_closed(self):
        self.handler_class.fetcher = staticmethod(
            lambda _authorization: (_ for _ in ()).throw(
                AdapterError("simulated failure")
            )
        )
        status, _, body = self.request(
            headers={"Authorization": "Bearer test-token"}
        )
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(body)["error"],
            "upstream_userinfo_failed",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and verify they fail**

Run:

```bash
cd /usr/local/lib/grafana-discord-userinfo
python3 -m unittest -v test_adapter.py
```

Expected: failure with `ModuleNotFoundError: No module named 'adapter'`.

- [ ] **Step 4: Implement the minimal adapter**

Create `/usr/local/lib/grafana-discord-userinfo/adapter.py` with:

```python
#!/usr/bin/python3
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BIND_HOST = "127.0.0.1"
BIND_PORT = 9080
DISCORD_USERINFO_URL = "https://discord.com/api/v10/users/@me"
MAX_RESPONSE_BYTES = 65536
UPSTREAM_TIMEOUT_SECONDS = 5
BEARER_PATTERN = re.compile(r"^Bearer [^\s]+$")


class AdapterError(Exception):
    pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def normalize_discord_user(payload):
    if not isinstance(payload, dict):
        raise AdapterError("Discord UserInfo was not an object")

    for field in ("id", "username", "email"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"Discord UserInfo lacked {field}")

    if payload.get("verified") is not True:
        raise AdapterError("Discord email was not verified")

    normalized = dict(payload)
    normalized["sub"] = payload["id"]
    return normalized


def fetch_discord_user(authorization):
    if not BEARER_PATTERN.fullmatch(authorization):
        raise AdapterError("Missing or invalid bearer token")

    request = Request(
        DISCORD_USERINFO_URL,
        headers={
            "Accept": "application/json",
            "Authorization": authorization,
            "User-Agent": "grafana-discord-userinfo/1.0",
        },
        method="GET",
    )

    try:
        with urlopen(
            request,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        ) as response:
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if content_type != "application/json":
                raise AdapterError(
                    "Discord UserInfo was not JSON"
                )
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise AdapterError("Discord UserInfo request failed") from error

    if len(body) > MAX_RESPONSE_BYTES:
        raise AdapterError("Discord UserInfo response was too large")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterError("Discord UserInfo JSON was invalid") from error

    return normalize_discord_user(payload)


class UserInfoHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "grafana-discord-userinfo"
    sys_version = ""
    fetcher = staticmethod(fetch_discord_user)

    def log_message(self, _format, *_args):
        return

    def send_json(self, status, payload):
        body = json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/userinfo":
            self.send_json(404, {"error": "not_found"})
            return

        authorization = self.headers.get("Authorization", "")
        if not BEARER_PATTERN.fullmatch(authorization):
            self.send_json(
                401,
                {"error": "missing_bearer_token"},
            )
            return

        try:
            payload = self.fetcher(authorization)
        except AdapterError:
            print(
                "Discord UserInfo request or validation failed",
                file=sys.stderr,
                flush=True,
            )
            self.send_json(
                502,
                {"error": "upstream_userinfo_failed"},
            )
            return
        except Exception as error:
            print(
                "Unexpected UserInfo adapter error: "
                f"{type(error).__name__}",
                file=sys.stderr,
                flush=True,
            )
            self.send_json(
                500,
                {"error": "internal_error"},
            )
            return

        self.send_json(200, payload)

    def method_not_allowed(self):
        self.send_json(405, {"error": "method_not_allowed"})

    do_POST = method_not_allowed
    do_PUT = method_not_allowed
    do_PATCH = method_not_allowed
    do_DELETE = method_not_allowed
    do_HEAD = method_not_allowed


def main():
    server = ThreadingHTTPServer(
        (BIND_HOST, BIND_PORT),
        UserInfoHandler,
    )
    print(
        f"Listening on {BIND_HOST}:{BIND_PORT}",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the complete test suite**

Run:

```bash
cd /usr/local/lib/grafana-discord-userinfo
python3 -m unittest -v test_adapter.py
```

Expected: all 10 tests pass with `OK`.

- [ ] **Step 6: Compile-check and record checksums**

Run:

```bash
python3 -m py_compile \
  /usr/local/lib/grafana-discord-userinfo/adapter.py \
  /usr/local/lib/grafana-discord-userinfo/test_adapter.py
sha256sum \
  /usr/local/lib/grafana-discord-userinfo/adapter.py \
  /usr/local/lib/grafana-discord-userinfo/test_adapter.py
```

Expected: compile exits zero and two checksums are printed.

### Task 3: Install and Verify the systemd Service

- [ ] **Step 1: Create the unprivileged service account**

Run:

```bash
id grafana-oauth >/dev/null 2>&1 ||
  useradd --system --user-group --home-dir /nonexistent \
    --shell /usr/sbin/nologin grafana-oauth
chown -R root:root /usr/local/lib/grafana-discord-userinfo
chmod 0755 /usr/local/lib/grafana-discord-userinfo
chmod 0644 \
  /usr/local/lib/grafana-discord-userinfo/adapter.py \
  /usr/local/lib/grafana-discord-userinfo/test_adapter.py
```

- [ ] **Step 2: Create the systemd unit**

Create `/etc/systemd/system/grafana-discord-userinfo.service` with:

```ini
[Unit]
Description=Grafana Discord UserInfo compatibility adapter
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=grafana-oauth
Group=grafana-oauth
WorkingDirectory=/usr/local/lib/grafana-discord-userinfo
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 -I /usr/local/lib/grafana-discord-userinfo/adapter.py
Restart=on-failure
RestartSec=2s
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
CapabilityBoundingSet=
AmbientCapabilities=

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Validate, enable, and start the unit**

Run:

```bash
systemd-analyze verify \
  /etc/systemd/system/grafana-discord-userinfo.service
systemctl daemon-reload
systemctl enable --now grafana-discord-userinfo.service
systemctl is-enabled grafana-discord-userinfo.service
systemctl is-active grafana-discord-userinfo.service
```

Expected: no verification errors, followed by `enabled` and `active`.

- [ ] **Step 4: Verify loopback binding and fail-closed behavior**

Run:

```bash
ss -ltnp 'sport = :9080'
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:9080/userinfo
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:9080/other
curl --silent --request POST --output /dev/null \
  --write-out '%{http_code}\n' \
  http://127.0.0.1:9080/userinfo
```

Expected:

- Listener is `127.0.0.1:9080`, not `0.0.0.0:9080` or `[::]:9080`.
- Missing bearer token returns `401`.
- Wrong path returns `404`.
- POST returns `405`.

### Task 4: Validate the Adapter Against Discord

- [ ] **Step 1: Capture the most recent token without printing it**

Perform one Discord OAuth attempt if there is no recent token, then run:

```bash
DISCORD_TOKEN="$(
  journalctl -u grafana-server --since '-15 minutes' -o cat |
  sed -n 's/.*token is not in JWT format: \([^"]*\)".*/\1/p' |
  tail -n 1
)"
test -n "$DISCORD_TOKEN"
```

Expected: `test` exits zero and nothing prints.

- [ ] **Step 2: Verify normalized identity without printing email or token**

Run:

```bash
curl --silent --show-error --fail \
  -H "Authorization: Bearer $DISCORD_TOKEN" \
  http://127.0.0.1:9080/userinfo |
  jq '{
    id,
    sub,
    id_matches_sub: (.id == .sub),
    username_present: ((.username // "") != ""),
    email_present: ((.email // "") != ""),
    verified
  }'
unset DISCORD_TOKEN
```

Expected:

```json
{
  "id": "DISCORD_ADMIN_USER_ID",
  "sub": "DISCORD_ADMIN_USER_ID",
  "id_matches_sub": true,
  "username_present": true,
  "email_present": true,
  "verified": true
}
```

- [ ] **Step 3: Check adapter logs for sensitive output**

Run:

```bash
journalctl -u grafana-discord-userinfo.service \
  --since '-15 minutes' --no-pager
```

Expected: startup status only. No bearer token, authorization header, email,
or Discord JSON body appears.

### Task 5: Switch Grafana UserInfo to the Adapter

- [ ] **Step 1: Change only the UserInfo URL**

Using the preserved local administrator session, open:

```text
Administration → Authentication → Generic OAuth
```

Change:

```text
API URL / UserInfo URL:
http://127.0.0.1:9080/userinfo
```

Do not change the scopes, Teams URL, team IDs, attribute paths, role expression,
strict mode, or server-admin assignment setting. Save and expect HTTP `204`
from `PUT /api/v1/sso-settings/generic_oauth`.

- [ ] **Step 2: Verify the effective setting without exposing secrets**

Run:

```bash
sqlite3 -noheader /var/lib/grafana/grafana.db "
SELECT json_extract(settings, '\$.api_url')
FROM sso_setting
WHERE provider = 'generic_oauth'
  AND is_deleted = 0;
"
```

Expected:

```text
http://127.0.0.1:9080/userinfo
```

- [ ] **Step 3: Verify Grafana remains healthy**

Run:

```bash
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health | jq '{database,version}'
```

Expected: Grafana is active and database is `ok`.

### Task 6: Migrate the Existing OAuth Identity

- [ ] **Step 1: Stop Grafana and verify the migration preconditions**

Run:

```bash
systemctl stop grafana-server

sqlite3 -header -column /var/lib/grafana/grafana.db "
SELECT user_id, auth_module, quote(auth_id) AS auth_id
FROM user_auth
WHERE user_id = GRAFANA_USER_ID
   OR (
     auth_module = 'oauth_generic_oauth'
     AND auth_id = 'DISCORD_ADMIN_USER_ID'
   );
"
```

Expected: exactly one row for the user identified by `GRAFANA_USER_ID` with
`auth_id` equal to `''`. Stop if a
different user already owns `DISCORD_ADMIN_USER_ID`.

- [ ] **Step 2: Update exactly one row in one transaction**

Run:

```bash
sqlite3 -bail /var/lib/grafana/grafana.db <<'SQL'
BEGIN IMMEDIATE;
UPDATE user_auth
SET auth_id = 'DISCORD_ADMIN_USER_ID'
WHERE user_id = GRAFANA_USER_ID
  AND auth_module = 'oauth_generic_oauth'
  AND auth_id = '';
SELECT changes() AS rows_changed;
COMMIT;
SQL
```

Expected: `rows_changed` is `1`. If it is not `1`, do not continue to login
testing; use Task 9 rollback.

- [ ] **Step 3: Verify identity uniqueness and database integrity**

Run:

```bash
sqlite3 -header -column /var/lib/grafana/grafana.db "
SELECT
  ua.user_id,
  u.login,
  ua.auth_module,
  quote(ua.auth_id) AS auth_id,
  length(ua.auth_id) AS auth_id_length
FROM user_auth AS ua
JOIN user AS u ON u.id = ua.user_id
WHERE ua.auth_module = 'oauth_generic_oauth';
"

sqlite3 /var/lib/grafana/grafana.db 'PRAGMA integrity_check;'
```

Expected exactly:

```text
GRAFANA_USER_ID  grafana-admin-user  oauth_generic_oauth  'DISCORD_ADMIN_USER_ID'  <length of configured Discord user ID>
ok
```

- [ ] **Step 4: Start Grafana and verify health**

Run:

```bash
systemctl start grafana-server
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health | jq '{database,version}'
```

Expected: Grafana is active and database is `ok`.

### Task 7: Verify Authentication and Authorization

Security execution note: after Task 6, perform Task 8 Steps 1-3 before the
first verification login. This prevents Grafana from journaling another opaque
Discord bearer token. Perform Task 8 Step 4 together with Task 7 after that
login.

- [ ] **Step 1: Revoke the exposed Discord grant**

In Discord, open:

```text
User Settings → Authorized Apps
```

Remove the Grafana application. Do this before the verification login so
Discord issues a fresh token with the approved scopes.

- [ ] **Step 2: Verify the server-administrator account**

Log in through Discord as user `DISCORD_ADMIN_USER_ID`.

Expected:

- Login succeeds.
- The account can open Grafana server administration.
- The missing-`sub` warning does not appear.
- No user-sync error appears.

Run:

```bash
journalctl -u grafana-server --since '-10 minutes' --no-pager |
  grep -E 'generic_oauth|authn.service|user.sync|Request Completed'
```

Expected: successful OAuth callback with no `Missing sub claim`, no
`unable to create user`, and no team-membership or role-mapping failure.

- [ ] **Step 3: Verify stored identity and administrator state**

Run:

```bash
sqlite3 -header -column /var/lib/grafana/grafana.db "
SELECT
  u.id,
  u.login,
  u.is_admin,
  ua.auth_module,
  ua.auth_id
FROM user AS u
JOIN user_auth AS ua ON ua.user_id = u.id
WHERE u.id = GRAFANA_USER_ID
  AND ua.auth_module = 'oauth_generic_oauth';
"
```

Expected:

```text
id=GRAFANA_USER_ID
login=grafana-admin-user
is_admin=1
auth_id=DISCORD_ADMIN_USER_ID
```

- [ ] **Step 4: Verify Viewer access**

Use a non-administrator Discord test account holding either role
`DISCORD_VIEWER_ROLE_ID_1` or `DISCORD_VIEWER_ROLE_ID_2`.

Expected:

- Login succeeds.
- Grafana organization role is Viewer.
- Server administration is unavailable.
- Its `user_auth.auth_id` equals its Discord user ID and is non-empty.

- [ ] **Step 5: Verify deny-by-default**

Use a Discord test account in server `DISCORD_GUILD_ID` that holds neither
approved Viewer role.

Expected:

- Login is denied.
- Grafana does not create a usable account or grant a default role.
- Logs identify team-membership denial without containing a bearer token after
  Task 8 is complete.

### Task 8: Stop Grafana From Journaling Discord Bearer Tokens

- [ ] **Step 1: Inspect existing logger filters**

Run:

```bash
grep -nE '^\[log\]|^[[:space:]]*filters[[:space:]]*=' \
  /etc/grafana/grafana.ini
```

Record the current `[log] filters` value. Do not replace unrelated filters.

- [ ] **Step 2: Merge the OAuth logger filter**

Run this exact line-oriented update. It preserves all unrelated logger filters,
file ownership, and file mode:

```bash
test ! -e /etc/grafana/grafana.ini.pre-oauth-log-filter
cp --preserve=all /etc/grafana/grafana.ini \
  /etc/grafana/grafana.ini.pre-oauth-log-filter

python3 - /etc/grafana/grafana.ini <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
section_pattern = re.compile(r"^\s*\[([^\]]+)\]\s*$")
filter_pattern = re.compile(r"^\s*filters\s*=", re.IGNORECASE)

log_start = None
log_end = len(lines)
for index, line in enumerate(lines):
    match = section_pattern.match(line)
    if not match:
        continue
    if match.group(1).strip().lower() == "log":
        log_start = index
        continue
    if log_start is not None and index > log_start:
        log_end = index
        break

if log_start is None:
    raise SystemExit("[log] section not found")

filter_indexes = [
    index
    for index in range(log_start + 1, log_end)
    if filter_pattern.match(lines[index])
]
if len(filter_indexes) > 1:
    raise SystemExit("multiple active [log] filters lines found")

new_filter = "oauth.generic_oauth:error"
if filter_indexes:
    filter_index = filter_indexes[0]
    current = lines[filter_index].split("=", 1)[1].strip()
    entries = [
        entry.strip()
        for entry in current.split(",")
        if entry.strip()
        and not entry.strip().startswith("oauth.generic_oauth:")
    ]
    entries.append(new_filter)
    lines[filter_index] = "filters = " + ",".join(entries) + "\n"
else:
    lines.insert(log_start + 1, f"filters = {new_filter}\n")

metadata = path.stat()
temporary = path.with_name(path.name + ".oauth-filter.tmp")
temporary.write_text("".join(lines), encoding="utf-8")
os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
os.chown(temporary, metadata.st_uid, metadata.st_gid)
os.replace(temporary, path)
PY

grep -nE '^\[log\]|^[[:space:]]*filters[[:space:]]*=' \
  /etc/grafana/grafana.ini
```

Expected: the active `[log]` filter list contains exactly one
`oauth.generic_oauth:error` entry, and every previously configured filter is
still present.

- [ ] **Step 3: Restart and verify health**

Run:

```bash
systemctl restart grafana-server
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health | jq '{database,version}'
```

Expected: Grafana is active and database is `ok`.

- [ ] **Step 4: Verify OAuth warnings no longer expose a token**

Perform one successful OAuth login, then run:

```bash
journalctl -u grafana-server --since '-10 minutes' --no-pager |
  grep -F 'token is not in JWT format' &&
  echo 'FAIL: bearer token warning is still present' ||
  echo 'PASS: bearer token warning is suppressed'
```

Expected:

```text
PASS: bearer token warning is suppressed
```

Also confirm the successful request is still visible:

```bash
journalctl -u grafana-server --since '-10 minutes' --no-pager |
  grep -E 'authn.service|Request Completed'
```

### Task 9: Rollback Procedure

Use this task only if migration, startup, or OAuth verification fails.

- [ ] **Step 1: Stop both services**

Run:

```bash
systemctl stop grafana-server
systemctl stop grafana-discord-userinfo.service
```

- [ ] **Step 2: Verify the backup before restoration**

Run:

```bash
sqlite3 /var/lib/grafana/grafana.db.pre-discord-sub \
  'PRAGMA integrity_check;'
```

Expected: `ok`.

- [ ] **Step 3: Restore the database recoverably**

Preserve the failed database for diagnosis, then restore:

```bash
mv /var/lib/grafana/grafana.db \
  /var/lib/grafana/grafana.db.failed-discord-sub
cp --preserve=mode,ownership,timestamps \
  /var/lib/grafana/grafana.db.pre-discord-sub \
  /var/lib/grafana/grafana.db
chown grafana:grafana /var/lib/grafana/grafana.db
sqlite3 /var/lib/grafana/grafana.db 'PRAGMA integrity_check;'
```

Expected: `ok`. The failed database remains recoverable at
`/var/lib/grafana/grafana.db.failed-discord-sub`.

- [ ] **Step 4: Start Grafana and verify recovery**

Run:

```bash
systemctl start grafana-server
systemctl is-active grafana-server
curl --silent --show-error --fail --insecure \
  https://127.0.0.1:3000/api/health | jq '{database,version}'
```

Expected: Grafana is active with database `ok`. The restored backup contains the
pre-change direct Discord `api_url` because it was created before the adapter
setting and identity migration.
