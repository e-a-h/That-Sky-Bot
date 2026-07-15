from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `customcommand` ADD `ephemeral` BOOL NOT NULL  DEFAULT 0;
        ALTER TABLE `customcommand` ADD `allowedcontext` SMALLINT NOT NULL  COMMENT 'all: 0
chat: 1
app: 2' DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `customcommand` DROP COLUMN `ephemeral`;
        ALTER TABLE `customcommand` DROP COLUMN `allowedcontext`;"""


MODELS_STATE = (
    "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"
)
