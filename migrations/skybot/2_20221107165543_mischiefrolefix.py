from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


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


MODELS_STATE = (
    "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"
    "AGb3KjTblRBzz+AyZJenE="
)
