# That-Sky-Bot
That Sky [Bot] for thatgamecompany and #thatskygame

## Deployment Checklist
1. Create channels for:
   * Rules
   * Welcome
   * Bug reports ios live
   * Bug reports ios beta
   * Bug reports android live
   * Bug reports android beta
1. Create member role
1. Create rules message and add **:candle:** reaction
1. Channel permissions:
   * Rules and welcome should be
     * **@everone:** - +read, -send, -add reaction
     * **bot:** +add reaction
   * Bug report channels should be
     * **@everone:** -read, -add reaction
     * **members:** +read
     * **bot:** +read, +add reaction
   * Any members-only channel should be
     * **@everyone:** -read
     * **members:** +read
1. Config file required. see config.example.json and fill in channel IDs, guild ID, role IDs