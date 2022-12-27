from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `bugreport` MODIFY COLUMN `platform` VARCHAR(100) NOT NULL;
        ALTER TABLE `bugreport` MODIFY COLUMN `branch` VARCHAR(20) NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `bugreport` MODIFY COLUMN `platform` VARCHAR(10) NOT NULL;
        ALTER TABLE `bugreport` MODIFY COLUMN `branch` VARCHAR(10) NOT NULL;"""
