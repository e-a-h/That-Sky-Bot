from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `mischiefrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `alias` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_mischiefrol_roleid_191a9e` (`roleid`, `guild_id`),
    CONSTRAINT `fk_mischief_guild_81d149aa` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_mischiefrol_guild_i_38e363` (`guild_id`)
) CHARACTER SET utf8mb4;;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `mischiefrole`;"""
