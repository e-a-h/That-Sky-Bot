-- upgrade --
CREATE TABLE IF NOT EXISTS `adminrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `guild_id` INT NOT NULL,
    `roleid` BIGINT NOT NULL,
    KEY `idx_adminrole_guild_i_1576b8` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `artchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `listenchannelid` BIGINT NOT NULL,
    `collectionchannelid` BIGINT NOT NULL,
    `tag` VARCHAR(30) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `attachments` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `report_id` INT NOT NULL,
    `url` VARCHAR(255) NOT NULL,
    KEY `idx_attachments_report__4bd92e` (`report_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `autoresponder` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `trigger` VARCHAR(300) NOT NULL,
    `response` VARCHAR(2000) NOT NULL,
    `flags` BIGINT NOT NULL,
    `chance` SMALLINT NOT NULL,
    `responsechannelid` BIGINT NOT NULL,
    `listenchannelid` BIGINT NOT NULL,
    `logchannelid` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `botadmin` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `userid` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreport` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `message_id` BIGINT NOT NULL UNIQUE,
    `attachment_message_id` BIGINT NOT NULL UNIQUE,
    `reporter` BIGINT NOT NULL,
    `platform` VARCHAR(10) NOT NULL,
    `platform_version` VARCHAR(20) NOT NULL,
    `branch` VARCHAR(10) NOT NULL,
    `app_version` VARCHAR(20) NOT NULL,
    `app_build` VARCHAR(20),
    `title` VARCHAR(330) NOT NULL,
    `steps` VARCHAR(1024) NOT NULL,
    `expected` VARCHAR(880) NOT NULL,
    `actual` VARCHAR(880) NOT NULL,
    `additional` VARCHAR(500) NOT NULL,
    `reported_at` BIGINT NOT NULL,
    `deviceinfo` VARCHAR(220)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreportingchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL UNIQUE,
    `guild_id` INT NOT NULL,
    `platform_id` INT NOT NULL,
    KEY `idx_bugreportin_guild_i_e13b1e` (`guild_id`),
    KEY `idx_bugreportin_platfor_fe0d79` (`platform_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreportingplatform` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `platform` VARCHAR(255) NOT NULL,
    `branch` VARCHAR(255) NOT NULL,
    KEY `idx_bugreportin_platfor_28f551` (`platform`),
    KEY `idx_bugreportin_branch_bddf35` (`branch`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `configchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `configname` VARCHAR(100) NOT NULL,
    `channelid` BIGINT NOT NULL,
    `serverid` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `countword` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `word` VARCHAR(300) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `customcommand` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `trigger` VARCHAR(20) NOT NULL,
    `response` VARCHAR(2000) NOT NULL,
    `deletetrigger` BOOL NOT NULL,
    `reply` BOOL NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `dropboxchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `sourcechannelid` BIGINT NOT NULL,
    `targetchannelid` BIGINT NOT NULL,
    `deletedelayms` SMALLINT NOT NULL,
    `sendreceipt` BOOL NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `guild` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `memberrole` BIGINT NOT NULL,
    `nonmemberrole` BIGINT NOT NULL,
    `mutedrole` BIGINT NOT NULL,
    `welcomechannelid` BIGINT NOT NULL,
    `ruleschannelid` BIGINT NOT NULL,
    `logchannelid` BIGINT NOT NULL,
    `entrychannelid` BIGINT NOT NULL,
    `rulesreactmessageid` BIGINT NOT NULL,
    `defaultlocale` VARCHAR(10) NOT NULL,
    `betarole` BIGINT NOT NULL,
    `maintenancechannelid` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillbylines` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `krill_config_id` INT NOT NULL,
    `byline` VARCHAR(100) NOT NULL,
    `type` SMALLINT NOT NULL,
    `channelid` BIGINT NOT NULL,
    `locale` VARCHAR(10) NOT NULL,
    KEY `idx_krillbyline_krill_c_95a61d` (`krill_config_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL,
    `serverid` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillconfig` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `guild_id` INT NOT NULL UNIQUE,
    `return_home_freq` SMALLINT NOT NULL,
    `shadow_roll_freq` SMALLINT NOT NULL,
    `krill_rider_freq` SMALLINT NOT NULL,
    `crab_freq` SMALLINT NOT NULL,
    `allow_text` BOOL NOT NULL,
    `monster_duration` SMALLINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `localization` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `guild_id` INT NOT NULL,
    `channelid` BIGINT NOT NULL,
    `locale` VARCHAR(10) NOT NULL,
    KEY `idx_localizatio_guild_i_2a3780` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `modrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `guild_id` INT NOT NULL,
    `roleid` BIGINT NOT NULL,
    KEY `idx_modrole_guild_i_cc7b59` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `oreoletters` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `token` VARCHAR(50) NOT NULL,
    `token_class` SMALLINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `oreomap` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `letter_o` SMALLINT NOT NULL,
    `letter_r` SMALLINT NOT NULL,
    `letter_e` SMALLINT NOT NULL,
    `letter_oh` SMALLINT NOT NULL,
    `letter_re` SMALLINT NOT NULL,
    `space_char` SMALLINT NOT NULL,
    `char_count` VARCHAR(50) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `reactwatch` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `watchremoves` BOOL NOT NULL,
    `muteduration` SMALLINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `repros` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `report_id` INT NOT NULL,
    `user` BIGINT NOT NULL,
    KEY `idx_repros_report__c7a8a7` (`report_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `trustedrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `guild_id` INT NOT NULL,
    `roleid` BIGINT NOT NULL,
    KEY `idx_trustedrole_guild_i_deb2b1` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `userpermission` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `guild_id` INT NOT NULL,
    `userid` BIGINT NOT NULL,
    `command` VARCHAR(200) NOT NULL,
    `allow` BOOL NOT NULL,
    KEY `idx_userpermiss_guild_i_3a0dc1` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `watchedemoji` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `watcher_id` INT NOT NULL,
    `emoji` VARCHAR(50),
    `log` BOOL NOT NULL,
    `remove` BOOL NOT NULL,
    `mute` BOOL NOT NULL,
    KEY `idx_watchedemoj_watcher_a04b30` (`watcher_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
) CHARACTER SET utf8mb4;
