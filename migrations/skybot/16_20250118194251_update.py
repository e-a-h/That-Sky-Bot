from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `dropboxview` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    CONSTRAINT `fk_dropboxv_guild_aa59d631` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_dropboxview_guild_i_3ef8fd` (`guild_id`)
) CHARACTER SET utf8mb4;
        CREATE TABLE IF NOT EXISTS `dropboxtarget` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL,
    `button_label` VARCHAR(100) NOT NULL UNIQUE DEFAULT 'Send a Report',
    `button_emoji` VARCHAR(100) NOT NULL  DEFAULT '✉',
    `button_style` SMALLINT NOT NULL  DEFAULT 1,
    `modal_title` VARCHAR(100) NOT NULL  DEFAULT 'Send to Skybot',
    `modal_label` VARCHAR(100) NOT NULL  DEFAULT 'Send a report to Skybot',
    `modal_placeholder` VARCHAR(100) NOT NULL  DEFAULT 'Enter your report here...',
    `dropboxview_id` INT NOT NULL,
    CONSTRAINT `fk_dropboxt_dropboxv_dee7b410` FOREIGN KEY (`dropboxview_id`) REFERENCES `dropboxview` (`id`) ON DELETE CASCADE,
    KEY `idx_dropboxtarg_dropbox_ce31cb` (`dropboxview_id`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `dropboxtarget`;
        DROP TABLE IF EXISTS `dropboxview`;"""


MODELS_STATE = (
    "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"
)
