# Discord server setup bot

Describes the server in a JSON file and makes Discord match it. Faster and less error-prone than
clicking through twenty channels, and re-runnable when the structure changes.

## Two rules, because this runs with admin on a real server

**It plans before it acts.** The default is a dry run — it prints exactly what it would do and
changes nothing. You need `--apply` to make it real.

**It never deletes.** Anything on the server but not in the config is listed as left alone. A
config file is a poor reason to destroy a channel with history in it.

Re-running is safe and boring: whatever already matches is skipped.

## Setup

Only you can do steps 1–3; they need your Discord account.

**1. Create the bot.** [discord.com/developers/applications](https://discord.com/developers/applications)
→ New Application → name it → **Bot** → **Reset Token** → copy it.

**2. Save the token** in `tools/discord-bot/.env` — git-ignored, never commit it:

```
DISCORD_TOKEN=paste-it-here
```

**3. Invite it.** OAuth2 → URL Generator → scope **bot** → permission **Administrator** → open the
generated URL and add it to your server.

Administrator is heavy-handed but simplest for a temporary bot that creates roles and sets
permissions. That is also why you should kick it afterwards.

**4. Get the server id.** Discord Settings → Advanced → Developer Mode on, then right-click the
server → Copy Server ID.

**5. Run it.**

```bash
pip install discord.py
cp server.example.json server.json      # then edit server.json
python bot.py --guild 123456789012345678
```

That prints the plan. Read it. Then:

```bash
python bot.py --guild 123456789012345678 --apply
```

**6. Kick the bot** when you are happy. Nothing here needs it to stay, and a dormant bot with
Administrator is a standing risk for no benefit. Re-invite it later if you want to restructure —
the config file is the thing worth keeping, not the bot.

## What the config can express

| key | meaning |
|---|---|
| `roles` | name, colour, whether it shows separately in the member list, mentionable, permissions |
| `categories` | a group of channels |
| `categories[].private_to` | hidden from `@everyone`, visible only to the named roles |
| `channels[].type` | `text` or `voice` |
| `channels[].topic` | the description under the channel name |
| `channels[].read_only_for` | those roles can read and react but not post — for announcements |

Roles are created before categories, so `private_to` can name a role the same file creates.

## Notes

**Existing things are not modified.** A role or channel that already exists is left exactly as it
is, even if the config disagrees. That is deliberate: silently rewriting permissions on a channel
people are using is worse than doing nothing and saying so. Delete it and re-run if you want it
rebuilt from the config.

**Order in the file is not order in Discord.** Discord sorts by its own position values; drag
things where you want them once, and re-runs will not move them.
