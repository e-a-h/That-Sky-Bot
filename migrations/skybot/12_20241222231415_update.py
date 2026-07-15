from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `adminrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `attachments` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `autoresponder_id` INT;
        ALTER TABLE `autoresponse` MODIFY COLUMN `autoresponder_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `platform_id` INT NOT NULL;
        ALTER TABLE `customcommand` ADD `elevated` SMALLINT NOT NULL  DEFAULT 0;
        ALTER TABLE `customcommand` ADD `autocomplete` BOOL NOT NULL  DEFAULT 0;
        ALTER TABLE `krillbylines` MODIFY COLUMN `krill_config_id` INT NOT NULL;
        ALTER TABLE `krillconfig` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `localization` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `modrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `repros` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `trustedrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `userpermission` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `watchedemoji` MODIFY COLUMN `watcher_id` INT NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `repros` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `modrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `adminrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `attachments` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `krillconfig` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `trustedrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `autoresponse` MODIFY COLUMN `autoresponder_id` INT NOT NULL;
        ALTER TABLE `krillbylines` MODIFY COLUMN `krill_config_id` INT NOT NULL;
        ALTER TABLE `localization` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `watchedemoji` MODIFY COLUMN `watcher_id` INT NOT NULL;
        ALTER TABLE `customcommand` DROP COLUMN `elevated`;
        ALTER TABLE `customcommand` DROP COLUMN `autocomplete`;
        ALTER TABLE `userpermission` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `platform_id` INT NOT NULL;
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `autoresponder_id` INT;"""


MODELS_STATE = (
    "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"
    "Nu6Y4qGUwKMmLXOJbbJ8b++j98Srdp"
)
