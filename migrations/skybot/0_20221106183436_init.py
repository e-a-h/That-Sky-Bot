from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `artchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `listenchannelid` BIGINT NOT NULL  DEFAULT 0,
    `collectionchannelid` BIGINT NOT NULL  DEFAULT 0,
    `tag` VARCHAR(30) NOT NULL  DEFAULT '',
    UNIQUE KEY `uid_artchannel_serveri_dacf81` (`serverid`, `listenchannelid`, `collectionchannelid`, `tag`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `autoresponder` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `trigger` VARCHAR(300) NOT NULL,
    `response` VARCHAR(2000) NOT NULL,
    `flags` SMALLINT NOT NULL  DEFAULT 0,
    `chance` SMALLINT NOT NULL  DEFAULT 10000,
    `responsechannelid` BIGINT NOT NULL  DEFAULT 0,
    `listenchannelid` BIGINT NOT NULL  DEFAULT 0,
    `logchannelid` BIGINT NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_autorespond_trigger_d7d834` (`trigger`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `botadmin` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `userid` BIGINT NOT NULL UNIQUE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreport` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `reporter` BIGINT NOT NULL,
    `message_id` BIGINT  UNIQUE,
    `attachment_message_id` BIGINT  UNIQUE,
    `platform` VARCHAR(10) NOT NULL,
    `platform_version` VARCHAR(20) NOT NULL,
    `branch` VARCHAR(10) NOT NULL,
    `app_version` VARCHAR(20) NOT NULL,
    `app_build` VARCHAR(20),
    `title` VARCHAR(330) NOT NULL,
    `deviceinfo` VARCHAR(100) NOT NULL,
    `steps` VARCHAR(1024) NOT NULL,
    `expected` VARCHAR(880) NOT NULL,
    `actual` VARCHAR(880) NOT NULL,
    `additional` VARCHAR(500) NOT NULL,
    `reported_at` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `attachments` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `url` VARCHAR(255) NOT NULL,
    `report_id` INT NOT NULL,
    UNIQUE KEY `uid_attachments_report__89548d` (`report_id`, `url`),
    CONSTRAINT `fk_attachme_bugrepor_0d8fd583` FOREIGN KEY (`report_id`) REFERENCES `bugreport` (`id`) ON DELETE CASCADE,
    KEY `idx_attachments_report__4bd92e` (`report_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreportingplatform` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `platform` VARCHAR(100) NOT NULL,
    `branch` VARCHAR(20) NOT NULL,
    UNIQUE KEY `uid_bugreportin_platfor_fb781e` (`platform`, `branch`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `configchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `configname` VARCHAR(100) NOT NULL,
    `channelid` BIGINT NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_configchann_confign_21c1ab` (`configname`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `countword` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `word` VARCHAR(300) NOT NULL,
    UNIQUE KEY `uid_countword_word_931444` (`word`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `customcommand` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `trigger` VARCHAR(20) NOT NULL,
    `response` VARCHAR(2000) NOT NULL,
    `deletetrigger` BOOL NOT NULL  DEFAULT 0,
    `reply` BOOL NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_customcomma_trigger_65c25c` (`trigger`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `dropboxchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `sourcechannelid` BIGINT NOT NULL,
    `targetchannelid` BIGINT NOT NULL  DEFAULT 0,
    `deletedelayms` SMALLINT NOT NULL  DEFAULT 0,
    `sendreceipt` BOOL NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_dropboxchan_serveri_7254d9` (`serverid`, `sourcechannelid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `guild` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL UNIQUE,
    `memberrole` BIGINT NOT NULL  DEFAULT 0,
    `nonmemberrole` BIGINT NOT NULL  DEFAULT 0,
    `mutedrole` BIGINT NOT NULL  DEFAULT 0,
    `betarole` BIGINT NOT NULL  DEFAULT 0,
    `welcomechannelid` BIGINT NOT NULL  DEFAULT 0,
    `ruleschannelid` BIGINT NOT NULL  DEFAULT 0,
    `logchannelid` BIGINT NOT NULL  DEFAULT 0,
    `entrychannelid` BIGINT NOT NULL  DEFAULT 0,
    `maintenancechannelid` BIGINT NOT NULL  DEFAULT 0,
    `rulesreactmessageid` BIGINT NOT NULL  DEFAULT 0,
    `defaultlocale` VARCHAR(10) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `adminrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_adminrole_roleid_457f6b` (`roleid`, `guild_id`),
    CONSTRAINT `fk_adminrol_guild_56368cba` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_adminrole_guild_i_1576b8` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreportingchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    `platform_id` INT NOT NULL,
    UNIQUE KEY `uid_bugreportin_guild_i_91e902` (`guild_id`, `platform_id`),
    CONSTRAINT `fk_bugrepor_guild_04eb4078` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_bugrepor_bugrepor_2f3979ee` FOREIGN KEY (`platform_id`) REFERENCES `bugreportingplatform` (`id`) ON DELETE CASCADE,
    KEY `idx_bugreportin_guild_i_e13b1e` (`guild_id`),
    KEY `idx_bugreportin_platfor_fe0d79` (`platform_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `channelid` BIGINT NOT NULL,
    UNIQUE KEY `uid_krillchanne_serveri_5da66e` (`serverid`, `channelid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillconfig` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `return_home_freq` SMALLINT NOT NULL  DEFAULT 0,
    `shadow_roll_freq` SMALLINT NOT NULL  DEFAULT 0,
    `krill_rider_freq` SMALLINT NOT NULL  DEFAULT 0,
    `crab_freq` SMALLINT NOT NULL  DEFAULT 0,
    `allow_text` BOOL NOT NULL  DEFAULT 1,
    `monster_duration` SMALLINT NOT NULL  DEFAULT 21600,
    `guild_id` INT NOT NULL UNIQUE,
    CONSTRAINT `fk_krillcon_guild_43a114df` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_krillconfig_guild_i_bc8ec8` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillbylines` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `byline` VARCHAR(100) NOT NULL,
    `type` SMALLINT NOT NULL  DEFAULT 0,
    `channelid` BIGINT NOT NULL  DEFAULT 0,
    `locale` VARCHAR(10) NOT NULL  DEFAULT '',
    `krill_config_id` INT NOT NULL,
    UNIQUE KEY `uid_krillbyline_krill_c_b18cc4` (`krill_config_id`, `byline`, `type`),
    CONSTRAINT `fk_krillbyl_krillcon_04799d75` FOREIGN KEY (`krill_config_id`) REFERENCES `krillconfig` (`id`) ON DELETE CASCADE,
    KEY `idx_krillbyline_krill_c_95a61d` (`krill_config_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `localization` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL  DEFAULT 0,
    `locale` VARCHAR(10) NOT NULL  DEFAULT '',
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_localizatio_guild_i_1e041d` (`guild_id`, `channelid`),
    CONSTRAINT `fk_localiza_guild_9f755aae` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_localizatio_guild_i_2a3780` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `modrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_modrole_roleid_b1b1c0` (`roleid`, `guild_id`),
    CONSTRAINT `fk_modrole_guild_62488d68` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_modrole_guild_i_cc7b59` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `oreoletters` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `token` VARCHAR(50) NOT NULL  DEFAULT '',
    `token_class` SMALLINT NOT NULL,
    UNIQUE KEY `uid_oreoletters_token_84fe18` (`token`, `token_class`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `oreomap` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `letter_o` SMALLINT NOT NULL  DEFAULT 1,
    `letter_r` SMALLINT NOT NULL  DEFAULT 2,
    `letter_e` SMALLINT NOT NULL  DEFAULT 3,
    `letter_oh` SMALLINT NOT NULL  DEFAULT 4,
    `letter_re` SMALLINT NOT NULL  DEFAULT 5,
    `space_char` SMALLINT NOT NULL  DEFAULT 6,
    `char_count` VARCHAR(50) NOT NULL  DEFAULT '{0,10}'
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `reactwatch` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL UNIQUE,
    `muteduration` SMALLINT NOT NULL  DEFAULT 600,
    `watchremoves` BOOL NOT NULL  DEFAULT 0
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `repros` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `user` BIGINT NOT NULL,
    `report_id` INT NOT NULL,
    UNIQUE KEY `uid_repros_user_34d996` (`user`, `report_id`),
    CONSTRAINT `fk_repros_bugrepor_b26170f5` FOREIGN KEY (`report_id`) REFERENCES `bugreport` (`id`) ON DELETE CASCADE,
    KEY `idx_repros_report__c7a8a7` (`report_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `trustedrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_trustedrole_roleid_215f34` (`roleid`, `guild_id`),
    CONSTRAINT `fk_trustedr_guild_7af9759e` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_trustedrole_guild_i_deb2b1` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `userpermission` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `userid` BIGINT NOT NULL,
    `command` VARCHAR(200) NOT NULL  DEFAULT '',
    `allow` BOOL NOT NULL  DEFAULT 1,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_userpermiss_userid_7b40ae` (`userid`, `command`),
    CONSTRAINT `fk_userperm_guild_24ce9edd` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_userpermiss_guild_i_3a0dc1` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `watchedemoji` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `emoji` VARCHAR(50) NOT NULL,
    `log` BOOL NOT NULL  DEFAULT 0,
    `remove` BOOL NOT NULL  DEFAULT 0,
    `mute` BOOL NOT NULL  DEFAULT 0,
    `watcher_id` INT NOT NULL,
    UNIQUE KEY `uid_watchedemoj_emoji_4203dc` (`emoji`, `watcher_id`),
    CONSTRAINT `fk_watchede_reactwat_b8aaa411` FOREIGN KEY (`watcher_id`) REFERENCES `reactwatch` (`id`) ON DELETE CASCADE,
    KEY `idx_watchedemoj_watcher_a04b30` (`watcher_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
    "Nz8b+PP/bV2MXg=="
)
