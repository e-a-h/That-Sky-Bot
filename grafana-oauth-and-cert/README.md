# Grafana OAuth and Certificate Templates

Reusable templates and implementation records for:

- serving Grafana over HTTPS with a Grafana-readable certificate copy;
- refreshing that copy from Certbot after renewal;
- adding an OpenID-compatible `sub` claim to Discord UserInfo;
- admitting users by Discord guild role;
- mapping one designated Discord user to Grafana server administrator.

This package is sanitized for version control. It contains no live certificate
chain, private key, OAuth secret, access token, email address, operational
transcript, or production identifier.

## Replace these placeholders

Before deploying, replace every occurrence of:

| Placeholder | Required value |
|---|---|
| `grafana.example.com` | Grafana's public hostname and Certbot certificate name |
| `grafana-host` | Human-readable server name used in documentation |
| `grafana-admin-user` | Non-secret example/login label used in tests and migration examples |
| `DISCORD_GUILD_ID` | Discord guild/server ID |
| `DISCORD_VIEWER_ROLE_ID_1` | First Discord role allowed to log in |
| `DISCORD_VIEWER_ROLE_ID_2` | Second Discord role allowed to log in |
| `DISCORD_ADMIN_USER_ID` | Discord user ID mapped to Grafana server administrator |
| `GRAFANA_USER_ID` | Existing Grafana database user ID used only by the migration example |

Confirm no placeholders remain before installing anything:

```bash
rg -n \
  'grafana\.example\.com|grafana-host|grafana-admin-user|DISCORD_[A-Z0-9_]+' \
  grafana-oauth-and-cert
```

## Package contents

```text
grafana-oauth-and-cert/
├── README.md
├── PACKAGE-MANIFEST.md
├── adapter/
│   ├── adapter.py
│   └── test_adapter.py
├── certbot/
│   └── grafana-cert-refresh
├── systemd/
│   └── grafana-discord-userinfo.service
└── supporting-records/
    ├── plans/
    │   ├── 2026-07-27-grafana-certbot-deploy-hook.md
    │   └── 2026-07-27-grafana-discord-userinfo-adapter.md
    └── specs/
        ├── 2026-07-27-grafana-certbot-deploy-hook-design.md
        └── 2026-07-27-grafana-discord-role-authorization-design.md
```

The Python files, service unit, and shell hook are reference templates derived
from a tested deployment. Review them against the target host's Python,
systemd, Grafana, Certbot, and filesystem versions before installation.

## Discord OAuth model

Grafana sends its UserInfo request to the adapter on
`http://127.0.0.1:9080/userinfo`. The adapter forwards the bearer token to
Discord `/api/v10/users/@me`, validates the profile, and returns it with:

```text
sub = id
```

Grafana separately retrieves the current guild-member record and uses its
`roles` array as the login admission gate.

Template Generic OAuth settings:

```text
auth_url = https://discord.com/oauth2/authorize
token_url = https://discord.com/api/oauth2/token
api_url = http://127.0.0.1:9080/userinfo
scopes = ["identify","email","guilds","guilds.members.read"]
login_attribute_path = username
email_attribute_path = email
teams_url = https://discord.com/api/v10/users/@me/guilds/DISCORD_GUILD_ID/member
team_ids = ["DISCORD_VIEWER_ROLE_ID_1","DISCORD_VIEWER_ROLE_ID_2"]
team_ids_attribute_path = roles
role_attribute_path = id == 'DISCORD_ADMIN_USER_ID' && 'GrafanaAdmin' || 'Viewer'
role_attribute_strict = true
allow_assign_grafana_admin = true
```

Users holding neither allowed role are denied. The designated administrator
must also hold at least one allowed role.

Do not store the OAuth client secret in this repository. Configure it through
Grafana's supported secret/configuration mechanism.

## Adapter installation targets

After reviewing and replacing placeholders:

```text
/usr/local/lib/grafana-discord-userinfo/adapter.py
/usr/local/lib/grafana-discord-userinfo/test_adapter.py
/etc/systemd/system/grafana-discord-userinfo.service
```

The service runs under an unprivileged `grafana-oauth` account and binds only to
`127.0.0.1:9080`.

Run the tests before installation:

```bash
cd grafana-oauth-and-cert/adapter
python3 -m unittest -v test_adapter.py
python3 -m py_compile adapter.py test_adapter.py
```

## Certificate deployment model

Grafana reads:

```text
/etc/grafana/certs/fullchain.pem
/etc/grafana/certs/privkey.pem
```

Recommended metadata:

```text
owner=root
group=grafana
mode=0640
```

The Certbot hook template installs at:

```text
/etc/letsencrypt/renewal-hooks/deploy/grafana-cert-refresh
```

It ignores unrelated renewal lineages, copies certificate material through
temporary files, validates the certificate and key, confirms that their public
keys match, atomically replaces Grafana's copies, restarts Grafana, and polls
the HTTPS health endpoint.

Validate the customized hook before installation:

```bash
/bin/sh -n grafana-oauth-and-cert/certbot/grafana-cert-refresh
```

Do not add `fullchain.pem`, `privkey.pem`, Certbot account data, or renewal
credentials to this repository.

## Supporting records

- [Certificate deploy-hook design](supporting-records/specs/2026-07-27-grafana-certbot-deploy-hook-design.md)
- [Certificate deploy-hook implementation plan](supporting-records/plans/2026-07-27-grafana-certbot-deploy-hook.md)
- [Discord role-authorization design](supporting-records/specs/2026-07-27-grafana-discord-role-authorization-design.md)
- [Discord UserInfo adapter implementation plan](supporting-records/plans/2026-07-27-grafana-discord-userinfo-adapter.md)

The supporting records are sanitized templates. Their example database IDs,
paths, and expected outputs must be reviewed for the target environment.
