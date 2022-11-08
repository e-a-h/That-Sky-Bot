from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` VARCHAR(100) NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` VARCHAR(100) NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` VARCHAR(100) NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` VARCHAR(100) NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` VARCHAR(100) NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` BIGINT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` BIGINT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` BIGINT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` BIGINT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `alias` BIGINT NOT NULL;"""
