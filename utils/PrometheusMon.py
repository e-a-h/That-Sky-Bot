import prometheus_client as prom


class PrometheusMon:
    def __init__(self, bot) -> None:
        self.command_counter = prom.Counter("command_counter", "Number of commands run", ["command_name", "guild_id"])
        self.word_counter = prom.Counter(
            "word_counter",
            "Count of occurrences of words in chat",
            ["word", "guild_name", "guild_id"]
        )

        self.guild_messages = prom.Counter("guild_messages", "What messages have been sent and by who", [
            "guild_id"
        ])

        self.user_message_raw_count = prom.Counter("user_message_raw_count",
                                                   "Raw count of member messages")
        self.bot_message_raw_count = prom.Counter("bot_message_raw_count",
                                                  "Raw count of bot messages")
        self.own_message_raw_count = prom.Counter("own_message_raw_count",
                                                  "Raw count of SkyBot messages")

        self.bot_guilds = prom.Gauge("bot_guilds", "How many guilds the bot is in")
        self.bot_guilds.set_function(lambda: len(bot.guilds))

        self.bot_welcome_mute = prom.Gauge("bot_welcome_mute", "How new members are temp-muted", ["guild_id"])

        self.bot_users = prom.Gauge("bot_users", "How many users the bot can see")
        self.bot_users.set_function(lambda: sum(len(g.members) for g in bot.guilds))

        self.bot_users_unique = prom.Gauge("bot_users_unique", "How many unique users the bot can see")
        self.bot_users_unique.set_function(lambda: len(bot.users))

        # self.bot_event_counts = prom.Counter("bot_event_counts", "Counts for each event", ["event_name"])

        self.bot_latency = prom.Gauge("bot_latency", "Current bot latency")
        self.bot_latency.set_function(lambda: bot.latency)

        self.songs_in_progress = prom.Gauge("songs_in_progress", "Number of songs currently in progress")
        self.songs_completed = prom.Counter("songs_completed", "Number of songs completed")

        # self.reports_completed = prom.Counter("", "")  # already handled by mysql report count
        self.bot_cannot_dm_member = prom.Counter("bot_cannot_dm_member", "Bot tried and failed to send DM to member")
        self.reports_in_progress = prom.Gauge("reports_in_progress", "Number of reports currently in progress")
        self.reports_started = prom.Counter("reports_started", "Number of reports started")
        self.reports_restarted = prom.Counter("reports_restarted", "Number of reports restarted")
        self.reports_abort_count = prom.Counter("reports_abort_count", "Number of reports aborted")
        self.report_incomplete_count = prom.Counter("report_incomplete_count", "Number of reports failed")

        self.reports_question_0_duration = prom.Gauge("report_question_duration_00",
                                                      "Report start question. User called to DM from channel")
        self.reports_question_1_duration = prom.Gauge("report_question_duration_01",
                                                      "question 1: android or ios?")
        self.reports_question_2_duration = prom.Gauge("report_question_duration_02",
                                                      "question 2: android/ios version")
        self.reports_question_3_duration = prom.Gauge("report_question_duration_03",
                                                      "question 3: hardware info")
        self.reports_question_4_duration = prom.Gauge("report_question_duration_04",
                                                      "question 4: stable or beta?")
        self.reports_question_5_duration = prom.Gauge("report_question_duration_05",
                                                      "question 5: sky app version")
        self.reports_question_6_duration = prom.Gauge("report_question_duration_06",
                                                      "question 6: sky app build number")
        self.reports_question_7_duration = prom.Gauge("report_question_duration_07",
                                                      "question 7: Title")
        self.reports_question_8_duration = prom.Gauge("report_question_duration_08",
                                                      "question 8: actual - defect behavior")
        self.reports_question_9_duration = prom.Gauge("report_question_duration_09",
                                                      "question 9: steps to reproduce")
        self.reports_question_10_duration = prom.Gauge("report_question_duration_10",
                                                       "question 10: expected behavior")
        self.reports_question_11_duration = prom.Gauge("report_question_duration_11",
                                                       "question 11: attachments y/n")
        self.reports_question_12_duration = prom.Gauge("report_question_duration_12",
                                                       "question 11: attachments")
        self.reports_question_13_duration = prom.Gauge("report_question_duration_13",
                                                       "question 12: additional info y/n")
        self.reports_question_14_duration = prom.Gauge("report_question_duration_14",
                                                       "question 12: additional info")
        self.reports_question_15_duration = prom.Gauge("report_question_duration_15",
                                                       "Final review question")
        self.reports_duration = prom.Gauge("report_duration",
                                           "Total time to finish report")
        self.reports_exit_question = prom.Histogram("report_exit_question",
                                                    "Last question answered (lower number is report failure)",
                                                    buckets=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15))
        self.reports_question_duration = prom.Histogram("reports_question_duration",
                                                        "Question response time",
                                                        buckets=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15))
        self.auto_responder_count = prom.Counter("autor_responder_count",
                                                 "Auto-responder total triggers")
        self.auto_responder_mod_pass = prom.Counter("auto_responder_mod_pass",
                                                    "Auto-responder - mod action: pass")
        self.auto_responder_mod_manual = prom.Counter("auto_responder_mod_manual",
                                                      "Auto-responder - mod action: manual intervention")
        self.auto_responder_mod_auto = prom.Counter("auto_responder_mod_auto",
                                                    "Auto-responder - mod action: auto-respond")
        self.auto_responder_mod_delete_trigger = prom.Counter("auto_responder_mod_delete_trigger",
                                                              "Auto-responder - mod action: delete trigger")

        bot.metrics_reg.register(self.command_counter)
        bot.metrics_reg.register(self.word_counter)
        bot.metrics_reg.register(self.guild_messages)
        bot.metrics_reg.register(self.user_message_raw_count)
        bot.metrics_reg.register(self.bot_message_raw_count)
        bot.metrics_reg.register(self.own_message_raw_count)
        bot.metrics_reg.register(self.bot_welcome_mute)
        bot.metrics_reg.register(self.bot_guilds)
        bot.metrics_reg.register(self.bot_users)
        bot.metrics_reg.register(self.bot_users_unique)
        bot.metrics_reg.register(self.bot_latency)
        # bot.metrics_reg.register(self.bot_event_counts)

        bot.metrics_reg.register(self.songs_in_progress)
        bot.metrics_reg.register(self.songs_completed)

        bot.metrics_reg.register(self.bot_cannot_dm_member)
        bot.metrics_reg.register(self.reports_in_progress)
        bot.metrics_reg.register(self.reports_started)
        bot.metrics_reg.register(self.reports_restarted)
        bot.metrics_reg.register(self.reports_abort_count)
        bot.metrics_reg.register(self.report_incomplete_count)
        bot.metrics_reg.register(self.reports_question_0_duration)
        bot.metrics_reg.register(self.reports_question_1_duration)
        bot.metrics_reg.register(self.reports_question_2_duration)
        bot.metrics_reg.register(self.reports_question_3_duration)
        bot.metrics_reg.register(self.reports_question_4_duration)
        bot.metrics_reg.register(self.reports_question_5_duration)
        bot.metrics_reg.register(self.reports_question_6_duration)
        bot.metrics_reg.register(self.reports_question_7_duration)
        bot.metrics_reg.register(self.reports_question_8_duration)
        bot.metrics_reg.register(self.reports_question_9_duration)
        bot.metrics_reg.register(self.reports_question_10_duration)
        bot.metrics_reg.register(self.reports_question_11_duration)
        bot.metrics_reg.register(self.reports_question_12_duration)
        bot.metrics_reg.register(self.reports_question_13_duration)
        bot.metrics_reg.register(self.reports_question_14_duration)
        bot.metrics_reg.register(self.reports_question_15_duration)
        bot.metrics_reg.register(self.reports_duration)
        bot.metrics_reg.register(self.reports_exit_question)
        bot.metrics_reg.register(self.reports_question_duration)  # TODO
        bot.metrics_reg.register(self.auto_responder_count)
        bot.metrics_reg.register(self.auto_responder_mod_pass)
        bot.metrics_reg.register(self.auto_responder_mod_manual)
        bot.metrics_reg.register(self.auto_responder_mod_auto)
        bot.metrics_reg.register(self.auto_responder_mod_delete_trigger)
