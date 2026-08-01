# AutoResponder Subscribe — Design

Date: 2026-08-01
Component: `cogs/AutoResponders.py`, `utils/Database.py`

## Goal

Let moderators subscribe themselves to an AutoResponder (AR) rule and receive an
alert in a channel whenever that rule matches a message. Replaces the sketch
TODO in `AutoResponders.py` (`# TODO: ar subscribe`).

Subscriptions are **self-service and mod-only** (the cog's existing `cog_check`
already restricts every `@autor` command to moderators). A subscriber can only
sign themselves up.

## Decisions (locked)

- Alerts post to a **channel** (not DM). Default target `Guild.logchannelid`,
  overridable per subscription.
- Subscription record maps **subscriber id → AR id** (FK), plus target channel
  and cooldown. No trigger string is stored.
- **Content-leak mitigation** is a per-match visibility gate plus mod choice of
  target channel (see Visibility).
- Cooldown floor is **5 seconds**. The `cooldown` arg is an integer, coerced to
  `max(floor, value)` **at input** so stored/displayed values are always ≥ floor.
  The same `max(floor, ...)` is reapplied at evaluation as a defensive guard.
  Default is 5.
- Alerts never ping `@everyone` or roles.

## Data model

New model in `utils/Database.py`, styled after `AutoResponderChannel`:

```python
class AutoResponderSubscription(AbstractBaseModel):
    autoresponder = ForeignKeyField(f'{APP_NAME}.AutoResponder',
                                    related_name='subscriptions',
                                    index=True)           # on_delete defaults to CASCADE
    subscriberid = BigIntField()
    targetchannelid = BigIntField(default=0)              # 0 => Guild.logchannelid
    cooldown = SmallIntField(default=5)                   # seconds (stored; floored at eval)

    class Meta:
        unique_together = (("autoresponder", "subscriberid"),)
```

- Cascade delete of subscriptions on AR removal comes free from the FK default;
  the existing `remove` command deletes the `AutoResponder` row, cascading.
- `unique_together(autoresponder, subscriberid)` → one subscription per (member, AR).
- Guild is derived via `autoresponder.serverid` (prefetch), not duplicated.
- Migration: add model, run `aerich migrate`; file lands in `migrations/skybot/`.

## In-memory cache

`self.subscriptions: dict[int, dict[int, list[SubEntry]]]`
(`guild_id → ar_id → [entries]`).

Loaded by a `reload_subscriptions` method at cog load and re-run after every
subscribe/unsubscribe (mirrors the `self.triggers` / `reload_triggers` pattern).

`SubEntry` is a runtime object (not persisted):

- `subscriber_id: int`
- `target_channel_id: int` — resolved at load (explicit id, else `Guild.logchannelid`)
- `cooldown: int` — stored value
- `last_alert_time: float` — dispatch state, init `0`
- `missed_count: int` — dispatch state, init `0`

Dispatch state is memory-only and resets on restart (acceptable).

### Load/refresh validation

Per row, invalid → `Logging.info` a skip line and exclude from the active cache
(DB row is kept, not pruned):

1. Member present in guild (`guild.get_member`).
2. Target channel resolvable (explicit id, else `Guild.logchannelid`): exists,
   is a text channel, bot can send there.
3. Member can `view_channel` the **target** channel.

## Dispatch (on_message)

Hook in the match loop of `on_message` (~`AutoResponders.py:1716`), right after
`my_event` is confirmed non-None, **independent** of the mod-action vs
public-response branch — subscribers are notified regardless of the rule's other
behavior. The whole notify step is wrapped in `try/except → Utils.handle_exception`
so it can never break the match loop.

New method `notify_subscribers(message, rule, my_event)`:

1. `entries = self.subscriptions[guild.id].get(rule.id)`; if none, return.
2. `source = message.channel`; `now = time.time()`.
3. For each active entry:
   - **Source-visibility gate:** if `source.permissions_for(member).view_channel`
     is false → skip entirely (no mention, no count). This is the leak gate: the
     subscriber never learns about a match in a channel they cannot see.
   - **Cooldown:** `effective = max(self.subscription_cooldown_floor_seconds, entry.cooldown)`.
     - `now - entry.last_alert_time < effective` → `entry.missed_count += 1`, no mention.
     - else → add to fire-list carrying its current `missed_count`; then set
       `entry.last_alert_time = now` and `entry.missed_count = 0`.
4. Group fire-list entries by resolved `target_channel_id`. For each target
   channel, send **one** alert: an embed describing the current match plus a
   content line mentioning that group, each annotated `@mod (N missed)` when
   `N > 0`.

An alert fires to a target channel only when ≥1 subscriber there is off-cooldown.
The embed shows the **current** message (the one that broke cooldown for the
mentioned subscriber(s)); earlier suppressed messages are counted, not shown.

### Alert format

Embed (reuse existing embed helpers):

- Title: trigger (rule short description)
- Field: matched token(s) + `my_event.trigger_message.jump_url`
- Field: message content, `Utils.clean`'d and truncated to ~1000 chars
- Field: author id (`my_event.author_id`)
- Footer: author name

Mentions ride in the message `content` (outside the embed) so they actually ping.

Sent with:

```python
allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=<subscriber Members>)
```

`users` scoped to exactly the intended subscriber `Member` objects — no
`@everyone`/role ping and no arbitrary-user ping even if content is crafted.

## Class constant

```python
subscription_cooldown_floor_seconds = 5
```

Added alongside the other `AutoResponders` class constants (e.g.
`raw_response_fields_per_embed`). Name is explicit about unit (seconds) and
meaning (floor / minimum), avoiding the "min = minutes" ambiguity.

## Commands (under `@autor`, mod-only)

- **`subscribe <trigger|id> [channel] [cooldown: int]`**
  - Resolve AR via `choose_trigger`.
  - Self-subscribe (subscriber = command author).
  - `cooldown` is an integer (seconds). Non-int input is rejected by the command
    parser. Values below the floor are coerced up:
    `cooldown = max(self.subscription_cooldown_floor_seconds, cooldown)` **at
    input**, so the stored and displayed value is always ≥ floor.
  - On unique-constraint collision `(subscriber, ar)`: prompt **replace / cancel**
    via the `Questions` dialog (as `set_trigger` does). Replace updates channel +
    cooldown.
  - Validate channel is viewable by caller and postable by bot.
  - `reload_subscriptions` after write.
- **`unsubscribe <trigger|id>`**
  - Resolve AR; delete the caller's own row; `reload_subscriptions`.
- **`subscriptions [trigger|id]`**
  - **Self-only** list. Each entry: trigger, target channel, cooldown. Optional
    arg filters to one AR.

All writes call `reload_subscriptions`, matching the `create` / `channels`
command pattern.

## Testing

- Model: create/read/unique-collision/cascade-on-AR-delete.
- Cooldown math: floor enforced (`max(5, configured)`); missed-count accrues
  during cooldown and resets on fire.
- Visibility gate: subscriber without `view_channel` on source is skipped
  entirely; content never posted where they'd see it via the alert.
- Grouping: multiple subscribers, mixed cooldown state, split across target
  channels → one alert per target, correct mentions + missed annotations.
- Allowed-mentions: `@everyone`/role tokens in content do not ping.
- Load validation: missing member / unresolvable target / no view perm → excluded
  and logged, DB row retained.

## Out of scope

- DM delivery.
- Subscribing other members (self-only only).
- Digest/coalesced alerts (chose simple cooldown instead).
- Persisting dispatch state (missed-count/last-alert) across restart.
