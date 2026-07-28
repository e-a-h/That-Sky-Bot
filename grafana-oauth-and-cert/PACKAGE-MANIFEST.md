# Package Manifest

## Included

| Path | Purpose |
|---|---|
| `.gitignore` | Prevents accidental addition of certificate, key, log, evidence, and cache files |
| `README.md` | Sanitized deployment overview and placeholder reference |
| `adapter/adapter.py` | Loopback Discord UserInfo compatibility adapter |
| `adapter/test_adapter.py` | Adapter validation and HTTP behavior tests |
| `certbot/grafana-cert-refresh` | Certbot deploy-hook template |
| `systemd/grafana-discord-userinfo.service` | Hardened systemd unit template |
| `supporting-records/specs/` | Sanitized design records |
| `supporting-records/plans/` | Sanitized implementation and rollback plans |

## Excluded

- Public or private certificate files
- Certbot account or renewal state
- Private keys
- OAuth client IDs and client secrets
- Discord access or refresh tokens
- Email addresses
- Production hostnames and account names
- Production Discord guild, role, and user IDs
- Operational logs, test transcripts, PIDs, timestamps, and health evidence
- Database files and database backups
- Integrity hashes from the original deployment

## Template status

All production-specific identifiers were replaced with placeholders. These
files are reusable templates, not byte-for-byte exports of a live server.
Replace and review every placeholder before deployment.
