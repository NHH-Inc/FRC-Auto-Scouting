"""Build out a Discord server from a description of what it should look like.

Clicking through Discord's UI to create twenty channels, six roles and their permissions is slow
and easy to get subtly wrong. This takes a JSON description and makes the server match it.

Two rules shape the whole thing, because this runs with admin on a server real people use.

**It plans before it acts.** The default is a dry run: it prints exactly what it would create and
change, and exits without touching anything. Applying requires `--apply`. Handing a script admin
and letting it run unseen is how a server loses a channel nobody meant to lose.

**It never deletes.** Anything present on the server but absent from the config is reported and
left alone. A config file is a poor reason to destroy a channel with history in it. If something
should really go, a person can delete it, having decided that deliberately.

Re-running is safe and dull: whatever already matches is skipped, so this is a convergence tool
rather than a one-shot script. That also makes it usable as "apply this change" later, not just
"set the server up once".

Setup, and the part only you can do:

  1. https://discord.com/developers/applications -> New Application -> Bot -> Reset Token, copy it
  2. Put it in tools/discord-bot/.env as DISCORD_TOKEN=...   (git-ignored; never commit a token)
  3. OAuth2 -> URL Generator -> scopes: bot -> permission: Administrator -> open the URL, invite
     it to your server
  4. python bot.py --guild <server id>              # plan only
     python bot.py --guild <server id> --apply      # make the changes
  5. When you are done, kick the bot. Nothing here needs it to stay.

Requires: pip install discord.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

try:
    import discord
except ImportError:  # pragma: no cover - the error should say what to do
    raise SystemExit("discord.py is not installed. Run: pip install discord.py")


HERE = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("_comment", None)
    return document


def load_token() -> str:
    """Token from the environment, or from a git-ignored .env beside this file."""
    token = os.environ.get("DISCORD_TOKEN", "")
    env = HERE / ".env"
    if not token and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DISCORD_TOKEN="):
                token = line.split("=", 1)[1].strip()
    if not token:
        raise SystemExit(
            "No DISCORD_TOKEN. Put it in tools/discord-bot/.env or the environment.\n"
            "Get one at https://discord.com/developers/applications -> your app -> Bot."
        )
    return token


class Plan:
    """What would change, gathered before anything is touched so it can be shown as a whole."""

    def __init__(self):
        self.actions: list[tuple[str, str]] = []
        self.untouched: list[str] = []

    def add(self, verb: str, what: str) -> None:
        self.actions.append((verb, what))

    def leave(self, what: str) -> None:
        self.untouched.append(what)

    def render(self, applying: bool) -> None:
        if not self.actions:
            print("  nothing to change -- the server already matches the config")
        for verb, what in self.actions:
            print(f"  {'APPLIED ' if applying else 'would   '}{verb:<8} {what}")
        if self.untouched:
            print("\n  present on the server but not in the config, LEFT ALONE:")
            for what in self.untouched:
                print(f"    {what}")
            print("  (delete these by hand if you actually want them gone)")


def parse_colour(value: str | None):
    if not value:
        return discord.Colour.default()
    return discord.Colour(int(value.lstrip("#"), 16))


def build_permissions(names: list[str]) -> discord.Permissions:
    perms = discord.Permissions.none()
    for name in names or []:
        if hasattr(perms, name):
            setattr(perms, name, True)
        else:
            print(f"  ! unknown permission '{name}' ignored")
    return perms


async def sync(client: discord.Client, guild_id: int, config: dict, apply: bool) -> int:
    guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
    if guild is None:
        print(f"  the bot is not in guild {guild_id}, or the id is wrong")
        return 1

    print(f"\nserver: {guild.name}\n")
    plan = Plan()

    # --- roles ---------------------------------------------------------------------------------
    existing_roles = {r.name: r for r in await guild.fetch_roles()}
    wanted_roles = {r["name"] for r in config.get("roles", [])}

    for spec in config.get("roles", []):
        name = spec["name"]
        if name in existing_roles:
            plan.leave(f"role     {name} (already exists, not modified)")
            continue
        plan.add("create", f"role     {name}")
        if apply:
            role = await guild.create_role(
                name=name,
                colour=parse_colour(spec.get("colour")),
                hoist=bool(spec.get("hoist", False)),
                mentionable=bool(spec.get("mentionable", False)),
                permissions=build_permissions(spec.get("permissions", [])),
                reason="Project Tengen server setup",
            )
            existing_roles[name] = role

    for name in existing_roles:
        if name not in wanted_roles and name != "@everyone":
            plan.leave(f"role     {name}")

    # --- categories and channels ---------------------------------------------------------------
    existing_categories = {c.name: c for c in guild.categories}
    wanted_channels: set[str] = set()

    for cat_spec in config.get("categories", []):
        cat_name = cat_spec["name"]
        category = existing_categories.get(cat_name)

        overwrites = {}
        private_to = cat_spec.get("private_to")
        if private_to:
            # A private category: hidden from everyone, visible to the named roles. Done at the
            # category so channels inherit it rather than each needing its own rule.
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            for role_name in private_to:
                role = existing_roles.get(role_name)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True)
                elif not apply:
                    print(f"  ! category {cat_name} wants role '{role_name}', "
                          f"which will exist once roles are created")

        if category is None:
            plan.add("create", f"category {cat_name}" + (" (private)" if private_to else ""))
            if apply:
                category = await guild.create_category(
                    cat_name, overwrites=overwrites,
                    reason="Project Tengen server setup")
                existing_categories[cat_name] = category
        else:
            plan.leave(f"category {cat_name} (already exists)")

        existing_here = {c.name: c for c in (category.channels if category else [])}
        for ch_spec in cat_spec.get("channels", []):
            ch_name = ch_spec["name"]
            wanted_channels.add(ch_name)
            if ch_name in existing_here:
                plan.leave(f"channel  #{ch_name}")
                continue

            kind = ch_spec.get("type", "text")
            plan.add("create", f"channel  #{ch_name}  ({kind}, in {cat_name})")
            if not apply or category is None:
                continue

            ch_overwrites = {}
            for role_name in ch_spec.get("read_only_for", []):
                role = guild.default_role if role_name == "@everyone" else existing_roles.get(role_name)
                if role:
                    # Readable by all, postable by none of them -- an announcements channel.
                    ch_overwrites[role] = discord.PermissionOverwrite(
                        send_messages=False, add_reactions=True, view_channel=True)

            if kind == "voice":
                await guild.create_voice_channel(
                    ch_name, category=category, overwrites=ch_overwrites,
                    reason="Project Tengen server setup")
            else:
                await guild.create_text_channel(
                    ch_name, category=category, topic=ch_spec.get("topic"),
                    overwrites=ch_overwrites,
                    reason="Project Tengen server setup")

    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
        if channel.name not in wanted_channels:
            plan.leave(f"channel  #{channel.name}")

    plan.render(apply)
    if not apply:
        print("\n  DRY RUN -- nothing was changed. Re-run with --apply to make it so.")
    else:
        print(f"\n  applied {len(plan.actions)} change(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guild", required=True, type=int, help="server id (right-click > Copy Server ID)")
    parser.add_argument("--config", type=Path, default=HERE / "server.json")
    parser.add_argument("--apply", action="store_true",
                        help="actually make the changes; without this it only prints the plan")
    args = parser.parse_args()

    config_path = args.config
    if not config_path.exists():
        example = HERE / "server.example.json"
        raise SystemExit(f"No {config_path.name}. Copy {example.name} to {config_path.name} and edit it.")

    config = load_config(config_path)
    token = load_token()

    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)
    status = {"code": 1}

    @client.event
    async def on_ready():
        # discord.py swallows exceptions raised inside event handlers, and log_handler=None
        # silences its logger, so a failure part-way through an apply would otherwise vanish and
        # look like the run simply stopping. Report it, loudly, and say what had already changed.
        try:
            status["code"] = await sync(client, args.guild, config, args.apply)
        except discord.Forbidden as error:
            print("")
            print(f"  REFUSED by Discord: {error.text}")
            print("  The bot lacks a permission it needs. Check its role has Administrator, and")
            print("  that the bot's role sits ABOVE the roles and categories it is managing --")
            print("  Discord ignores permissions from a role positioned below the target.")
            status["code"] = 1
        except Exception as error:
            import traceback
            print("")
            print(f"  FAILED: {type(error).__name__}: {error}")
            traceback.print_exc()
            status["code"] = 1
        finally:
            await client.close()

    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("Discord rejected the token. Reset it in the developer portal and retry.")
    return status["code"]


if __name__ == "__main__":
    raise SystemExit(main())
