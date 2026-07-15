from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `mischiefname` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(36) NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_mischiefnam_name_a3dbcd` (`name`, `guild_id`),
    CONSTRAINT `fk_mischief_guild_ecb1522f` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_mischiefnam_guild_i_afebf5` (`guild_id`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `mischiefname`;"""


MODELS_STATE = (
    "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"
)
