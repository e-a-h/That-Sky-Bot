from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `bugreport` MODIFY COLUMN `platform` VARCHAR(100) NOT NULL;
        ALTER TABLE `bugreport` MODIFY COLUMN `branch` VARCHAR(20) NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `bugreport` MODIFY COLUMN `platform` VARCHAR(10) NOT NULL;
        ALTER TABLE `bugreport` MODIFY COLUMN `branch` VARCHAR(10) NOT NULL;"""


MODELS_STATE = (
    "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"
    "WBa7zJtTblWh3w+A+NaHrT"
)
