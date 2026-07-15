from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


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


MODELS_STATE = (
    "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"
    "8slUHeLLjBm9xoU27UAY//ANcWhas="
)
