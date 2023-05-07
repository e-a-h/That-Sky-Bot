# Discord Guild Setup

This guide assumes the hosting discord guild uses native member onboarding. Rules verification and phone number requirement are highly recommended.

## Invite the Bot!

A Config file required. see config.example.json and fill in channel IDs, guild ID, role IDs, etc.  Go get your bot invite URL from the discord developer portal and use it to invite the bot into the server.

## Initial Guild Setup

For each of the roles and channels the bot will interact with, make notes of their IDs for use in commands and configs.

* Create a "**member**" role. This role will be assigned to members automatically when they speak. This can be helpful in tracking who has interacted in the server, among other things.
* Create a "**nonmember**" role. This role will be assigned to nonmembers? Maybe not.
* Create a "**muted**" role and configure as needed. This bot was written to work side-by-side with gearbot, and gearbot does a good job setting up a mute role. This bot **does not** configure the muted role, so if you're not using gearbot, you may have to manage mute permissions manually. This can be tedious and error-prone in a server with many channels, so gearbot or another bot that manages a muted role is highly recommended!
* Create channels:
  * Logging channel
  * Extra logging channels if needed
* Log Channel permissions
  * **@everone:** -read
  * **moderators/staff:** +read
  * **bot:** +read
* Channel configuration
  * Note all channel ids for later use. The bot supports one primary logging channel, configured with the following command:
    ```
    !guild set log_channel #channel_mention_or_id
    ```
* Other roles and channels need to be recorded for some features to work. Replace zeroes with actual role and channel IDs. 

```
!guild set member_role 0000000000000000
!guild set nonmember_role 0000000000000000
!guild set muted_role 0000000000000000
!guild set beta_role 0000000000000000
!guild set maintenance_channel 0000000000000000
```

## Bug Reporting Setup

### Bug platform and branch configuration:

Create database records for platforms and branches that can be used for reporting bugs. For any new platform or branch, changes to langs/en_US.yaml will be required.

For a single reporting platform/branch combination, use any name:
```
!bug platform add default default
```

For multiply platforms and branches, name each:
```
!bug platform add Android Beta
!bug platform add Android Stable
!bug platform add iOS Stable
!bug platform add Switch Beta
!bug platform add Switch Stable
```

### Create bug report channels per platform/branch

Channel permissions:
* Bug report channel permissions should prevent members from adding new messages or reacts. The bot needs channel visibility explicitly set. 
  * **@everone:**
    * -send messages
    * -add reaction
  * **bot:**
    * +view channel
    * +send messages
    * +add reaction

Configure channels for every platform/branch combination above. Note that you can use the same channel to receive reports for more than one platform/branch if desired.
   ```
  !bug channel add #mention-or-id Android Stable
   ```
Bug reporting maintenance channel
* Bug report maintenance channel permissions should hide the channel initially and prevent messaging and reacts
  * **@everone:** -add reaction
  * **bot:** +add reaction
  ```
  !guild set maintenance_channel #channel_mention_or_id
  ```

# Other documentation:
* [README](../README.md)
* [Deploying the Bot](deploy.md)
* [Server-side Maintenance](server_side_maintenance.md)
