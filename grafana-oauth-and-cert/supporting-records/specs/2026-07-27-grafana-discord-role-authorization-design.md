# Grafana Discord Role Authorization Design

> Supporting record in the `grafana-host` Grafana change package.

## Objective

Authorize Grafana users from one Discord server using Discord guild roles:

- Discord server `DISCORD_GUILD_ID` is the only server in scope.
- Discord roles `DISCORD_VIEWER_ROLE_ID_1` and `DISCORD_VIEWER_ROLE_ID_2`
  grant Grafana Viewer access.
- Discord user `DISCORD_ADMIN_USER_ID` receives Grafana server-administrator
  access when that user also holds at least one approved Viewer role.
- Users without an approved Viewer role are denied.
- No Discord role maps to Grafana Editor.

## Selected Architecture

Use Grafana Generic OAuth with a loopback-only UserInfo compatibility adapter.
No bot token or external identity broker is introduced.

The adapter receives Grafana's UserInfo request, forwards its bearer token to
Discord's `/users/@me` endpoint, validates the response, and returns the same
profile with `sub` set to Discord's stable `id`. Grafana's `teams_url` continues
to point directly to Discord's current-user guild-member endpoint for the
single authorized server. That endpoint returns a `roles` array, which Grafana
uses for its team-ID admission check.

The adapter is a dependency-free Python 3 systemd service. It binds only to
`127.0.0.1:9080`, accepts only `GET /userinfo`, stores no Discord credentials,
and never logs authorization headers or response bodies.

## Configuration Model

The intended effective Generic OAuth settings are:

```text
scopes = identify email guilds guilds.members.read
api_url = http://127.0.0.1:9080/userinfo
teams_url = https://discord.com/api/v10/users/@me/guilds/DISCORD_GUILD_ID/member
team_ids = ["DISCORD_VIEWER_ROLE_ID_1", "DISCORD_VIEWER_ROLE_ID_2"]
team_ids_attribute_path = roles
role_attribute_path = id == 'DISCORD_ADMIN_USER_ID' && 'GrafanaAdmin' || 'Viewer'
allow_assign_grafana_admin = true
role_attribute_strict = true
```

The settings are managed through Grafana's database-backed SSO configuration.
They must be changed through Grafana's authentication UI or SSO Settings API,
not by directly updating SQLite.

## Authorization Flow

1. Grafana redirects the user to Discord with the configured OAuth scopes.
2. Discord returns an access token.
3. Grafana calls the loopback adapter's `/userinfo` endpoint with the bearer
   token.
4. The adapter forwards the bearer token to Discord `/api/v10/users/@me`.
5. The adapter requires a successful JSON object containing non-empty `id`,
   `username`, and `email` fields plus `verified: true`, copies `id` to `sub`,
   and returns the normalized profile to Grafana.
6. Grafana uses `sub` as the stable external authentication ID.
7. Grafana calls
   `/api/v10/users/@me/guilds/DISCORD_GUILD_ID/member` with the same bearer
   token.
8. Grafana evaluates the returned `roles` array against the two configured
   `team_ids`.
9. A user holding neither role is denied before role assignment.
10. An admitted user whose Discord ID is `DISCORD_ADMIN_USER_ID` receives
   `GrafanaAdmin`.
11. Every other admitted user receives `Viewer`.

The administrator is deliberately subject to the same Viewer-role admission
gate. Removing both Viewer roles denies that account on its next OAuth
authentication.

## Security and Failure Behavior

- The adapter binds only to loopback and is unreachable from the network.
- The adapter accepts only `GET /userinfo`; every other path or method is
  rejected.
- The adapter requires a bearer authorization header but never logs or stores
  it.
- The adapter uses a short upstream timeout, limits response size, requires
  JSON, and returns an authentication failure for invalid Discord responses.
- The adapter runs as a dedicated unprivileged system user with systemd
  hardening and no writable application directory.
- Loopback HTTP is acceptable because both Grafana and the adapter run on the
  same host and the listener is not exposed beyond `127.0.0.1`.
- `guilds.members.read` is required to retrieve the current user's member
  record for the target Discord server.
- `allow_assign_grafana_admin` is enabled because the approved mapping can
  return `GrafanaAdmin`.
- `role_attribute_strict` is enabled so an invalid or missing role result fails
  closed instead of silently assigning a default role.
- A Discord 401, 403, missing guild membership, missing approved role, or
  malformed role response denies authentication.
- OAuth bearer tokens and authorization headers must not be copied into chat or
  diagnostic output.
- Grafana's `oauth.generic_oauth` logger is filtered at `error` after successful
  verification because its non-JWT warning includes Discord's opaque bearer
  token. Any existing `[log] filters` entries must be preserved when adding this
  logger-specific filter.
- Users must approve the expanded OAuth scope. Existing Discord grants should
  be revoked and reauthorized after the scope change.
- Discord role changes are reflected at the next OAuth authentication. They do
  not continuously revoke an already-established Grafana session.

## Rollout

1. Preserve a working local Grafana administrator session as a recovery path.
2. Record the current effective Generic OAuth settings without exposing the
   client secret.
3. Stop Grafana, create a timestamped SQLite backup, and restart Grafana before
   making configuration or identity changes.
4. Install and start the loopback UserInfo adapter.
5. Test the adapter with a temporary bearer token while emitting only
   non-sensitive boolean and identifier checks.
6. Point Grafana's DB-backed `api_url` to the adapter through Grafana's
   supported SSO configuration interface.
7. Stop Grafana. In one SQLite transaction, verify that no existing OAuth
   identity uses `DISCORD_ADMIN_USER_ID`, then update the empty
   `oauth_generic_oauth.auth_id` belonging to `GRAFANA_USER_ID` to that
   Discord ID.
8. Keep the previously configured Discord scopes, guild-member `teams_url`,
   Viewer role IDs, user-ID role expression, strict role handling, and
   server-admin assignment permission.
9. Start Grafana and verify health before attempting OAuth login.
10. Revoke the exposed Discord authorization grant, authorize a fresh token,
    and complete the authorization tests.
11. Merge `oauth.generic_oauth:error` into Grafana's existing `[log] filters`,
    restart Grafana, and verify that subsequent OAuth log entries do not expose
    the bearer token.

If migration or login verification fails, stop Grafana, restore the timestamped
database backup, restore the prior `api_url`, and restart Grafana.

## Verification

Verify all three authorization cases independently:

1. A non-administrator with either approved Viewer role can log in and has only
   Viewer access.
2. Discord user `DISCORD_ADMIN_USER_ID`, while holding an approved Viewer role,
   can log in and has Grafana server-administrator access.
3. A server member with neither approved Viewer role is denied.

Also verify:

- `/api/health` remains healthy.
- The adapter returns `sub` equal to Discord `id` without exposing the token or
  email.
- The `user_auth.auth_id` belonging to `GRAFANA_USER_ID` is exactly
  `DISCORD_ADMIN_USER_ID`.
- The missing-`sub` warning is absent.
- Grafana no longer writes Discord bearer tokens to its journal.
- OAuth logs contain no missing-scope, missing-email, team-membership, or
  role-mapping failures for approved users.
- Ordinary Viewers cannot access Grafana server-administration functions.
- Removing both Viewer roles from a test account causes denial after logout and
  a new OAuth login.

## Out of Scope

- Grafana Editor mapping.
- Discord roles from additional servers.
- Continuous mid-session permission revocation.
- A Discord bot, Authentik, or Keycloak deployment.
