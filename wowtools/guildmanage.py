import logging
import unicodedata

import dictdiffer
import discord
from discord.ext import tasks
from rapidfuzz import fuzz, process
from redbot.core import commands
from redbot.core.i18n import Translator, set_contextual_locales_from_guild
from redbot.core.utils.chat_formatting import humanize_list
from tabulate import tabulate

from .exceptions import InvalidBlizzardAPI

_ = Translator("WoWTools", __file__)
log = logging.getLogger("red.karlo-cogs.wowtools")


class GuildManage:
    @commands.group()
    @commands.admin()
    @commands.guild_only()
    async def gmset(self, ctx: commands.Context):
        """Configure guild management."""
        pass

    @gmset.command(name="rankstring")
    @commands.admin()
    async def gmset_rankstring(self, ctx: commands.Context, rank: int, *, rank_string: str):
        """Bind a rank to a string."""
        if rank not in range(1, 11):
            await ctx.send(_("Rank must be between 1 and 10."))
            return
        await self.config.guild(ctx.guild).guild_rankstrings.set_raw(rank, value=rank_string)
        await ctx.send(
            _("**{rank_string}** bound to **Rank {rank}**.").format(
                rank_string=rank_string, rank=rank
            )
        )

    @gmset.command(name="rankrole", hidden=True)
    @commands.admin()
    async def gmset_rankrole(self, ctx: commands.Context, rank: int, role: discord.Role):
        """Bind a rank to a role."""
        if rank not in range(1, 11):
            await ctx.send(_("Rank must be between 1 and 10."))
            return
        await self.config.guild(ctx.guild).guild_rankroles.set_raw(rank, value=role.id)
        await ctx.send(_("**{role}** bound to **Rank {rank}**.").format(role=role.name, rank=rank))

    @gmset.command(name="view")
    @commands.admin()
    async def gmset_view(self, ctx: commands.Context):
        """View guild rank settings."""
        guild: discord.Guild = ctx.guild
        rank_strings = await self.config.guild(guild).guild_rankstrings.get_raw()
        rank_roles = await self.config.guild(guild).guild_rankroles.get_raw()

        table_data = []
        for rank in range(1, 11):
            rank_string = rank_strings.get(str(rank), "")
            role_id = rank_roles.get(str(rank), None)
            role = guild.get_role(role_id) if role_id else None

            table_data.append([rank, rank_string, f"@{role.name}" if role else ""])

        headers = [_("Rank"), _("Rank String"), _("Rank Role")]
        table = tabulate(table_data, headers, tablefmt="plain")

        if ctx.channel.permissions_for(ctx.guild.me).embed_links:
            embed = discord.Embed(
                title=_("Rank Settings"),
                description=f"```{table}```",
                color=await ctx.embed_color(),
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Rank Settings:\n```{table}```")

    @gmset.command()
    @commands.admin()
    async def guild_name(self, ctx: commands.Context, *, guild_name: str):
        """Set the guild name to be used in the guild management commands."""
        try:
            async with ctx.typing():
                if guild_name is None:
                    await self.config.guild(ctx.guild).gmanage_guild.clear()
                    await ctx.send(_("Guild name cleared."))
                    return
                guild_name = guild_name.replace(" ", "-").lower()
                await self.config.guild(ctx.guild).gmanage_guild.set(guild_name)
            await ctx.send(_("Guild name set."))
        except Exception as e:
            await ctx.send(_("Command failed successfully. {e}").format(e=e))

    @gmset.command()
    @commands.admin()
    async def guild_realm(self, ctx: commands.Context, guild_realm: str | None = None):
        """Set the realm of the guild."""
        try:
            async with ctx.typing():
                if not guild_realm:
                    await self.config.guild(ctx.guild).gmanage_realm.clear()
                    await ctx.send(_("Guild realm cleared."))
                    return
                guild_realm = guild_realm.replace(" ", "-").lower()
                await self.config.guild(ctx.guild).gmanage_realm.set(guild_realm)
            await ctx.send(_("Guild realm set."))
        except Exception as e:
            await ctx.send(_("Command failed successfully. {e}").format(e=e))

    async def get_guild_roster(self, guild: discord.Guild) -> dict[str, int]:
        """
        Get guild roster from Blizzard's API.

        :param guild:
        :return: dict containing guild members and their rank
        """
        wow_guild_name: str = await self.config.guild(guild).gmanage_guild()
        wow_guild_name = wow_guild_name.lower()
        region: str = await self.config.guild(guild).region()
        realm: str = await self.config.guild(guild).gmanage_realm()
        realm = realm.lower()

        if not self.blizzard.get(region):
            raise InvalidBlizzardAPI
        async with self.blizzard.get(region) as wow_client:
            wow_client = wow_client.Retail
            guild_roster = await wow_client.Profile.get_guild_roster(
                name_slug=wow_guild_name, realm_slug=realm
            )

        roster: dict[str, int] = {
            f"{member['character']['name']}:{member['character']['realm']['slug']}": member["rank"]
            + 1
            for member in guild_roster["members"]
        }
        return roster

    @gmset.command()
    @commands.guild_only()
    async def guildlog(self, ctx: commands.Context, channel: discord.TextChannel | discord.Thread):
        """Set the channel for guild logs.

        This channel will be used to send messages when a member joins, leaves or is promoted/demoted within the in-game guild.
        """
        try:
            guild_roster = await self.get_guild_roster(ctx.guild)
        except InvalidBlizzardAPI:
            await ctx.send(
                _(
                    "The Blizzard API is not properly set up.\n"
                    "Create a client on https://develop.battle.net/ and then type in "
                    "`{prefix}set api blizzard client_id,whoops client_secret,whoops` "
                    "filling in `whoops` with your client's ID and secret."
                ).format(prefix=ctx.prefix)
            )
            return
        await self.config.guild(ctx.guild).guild_log_channel.set(channel.id)
        await self.config.guild(ctx.guild).guild_roster.set(guild_roster)
        await ctx.send(_("Guild log channel set to {channel}.").format(channel=channel.mention))

    @gmset.command()
    @commands.guild_only()
    async def guildlog_welcome(
        self, ctx: commands.Context, channel: discord.TextChannel | discord.Thread
    ):
        """Set the guild log welcome channel.

        When a user joins this server, a message will be sent to the provided channel with their in-game name and rank if the bot is able to find them.
        """
        await self.config.guild(ctx.guild).guild_log_welcome_channel.set(channel.id)
        try:
            guild_roster = await self.get_guild_roster(ctx.guild)
        except InvalidBlizzardAPI:
            await ctx.send(
                _(
                    "The Blizzard API is not properly set up.\n"
                    "Create a client on https://develop.battle.net/ and then type in "
                    "`{prefix}set api blizzard client_id,whoops client_secret,whoops` "
                    "filling in `whoops` with your client's ID and secret."
                ).format(prefix=ctx.prefix)
            )
            return
        await self.config.guild(ctx.guild).guild_roster.set(guild_roster)
        await ctx.send(_("Guild log channel set to {channel}.").format(channel=channel.mention))

    @tasks.loop(minutes=5)
    async def guild_log(self):
        for guild in self.bot.guilds:
            if await self.bot.cog_disabled_in_guild(self, guild):
                continue
            await set_contextual_locales_from_guild(self.bot, guild)

            guild_log_channel: int = await self.config.guild(guild).guild_log_channel()
            if guild_log_channel is None:
                continue
            guild_log_channel: discord.TextChannel | discord.Thread = guild.get_channel_or_thread(
                guild_log_channel
            )
            if guild_log_channel is None:
                continue

            log.debug("Comparing guild rosters.")
            try:
                current_roster = await self.get_guild_roster(guild)
            except InvalidBlizzardAPI:
                log.warning(
                    "The Blizzard API is not properly set up.\n"
                    "Create a client on https://develop.battle.net/ and then type in "
                    "`{prefix}set api blizzard client_id,whoops client_secret,whoops` "
                    "filling in `whoops` with your client's ID and secret."
                )
                return
            except RuntimeError:
                # idk, try again later
                return
            previous_roster: dict[str, int] = await self.config.guild(guild).guild_roster()

            # Have to do this now because the key will include the realm name, meaning comparing
            # means everything in previous will be different and it will send a message for
            # every single roster member.
            prev_for_diff: dict[str, int] = {}
            for name, rank in previous_roster.items():
                # Converting `character:realm` to just `character`
                prev_for_diff[name.split(":")[0]] = rank
            current_for_diff: dict[str, int] = {}
            for name, rank in current_roster.items():
                current_for_diff[name.split(":")[0]] = rank

            difference = list(dictdiffer.diff(prev_for_diff, current_for_diff))
            if not difference:
                log.debug("No difference in guild roster.")
                continue

            embeds = await self.get_event_embeds(difference, guild)
            await self.config.guild(guild).guild_roster.set(current_roster)

            for i in range((len(embeds) // 10) + 1):
                await guild_log_channel.send(embeds=embeds[i * 10 : (i + 1) * 10], silent=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if guild is None:
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if member.bot:
            return

        try:
            ingame_members, rank = await self.guess_ingame_member(guild, member.display_name)
        except (AttributeError, ValueError):
            return
        except InvalidBlizzardAPI:
            log.warning(
                "The Blizzard API is not properly set up.\n"
                "Create a client on https://develop.battle.net/ and then type in "
                "`{prefix}set api blizzard client_id,whoops client_secret,whoops` "
                "filling in `whoops` with your client's ID and secret."
            )
            return
        if not ingame_members:
            return

        desc = f"Discord: {member.mention}\n"
        desc += f"In-game: {humanize_list([name.split(':')[0] for name in ingame_members], style='or')}?\nRank: {rank}?\n"

        most_likely_member = ingame_members[0]
        rio_url = self.get_raiderio_url(
            realm=most_likely_member.split(":")[1],
            region=await self.config.guild(guild).region(),
            name=most_likely_member.split(":")[0],
        )
        wcl_url = self.get_warcraftlogs_url(
            realm=most_likely_member.split(":")[1],
            region=await self.config.guild(guild).region(),
            name=most_likely_member.split(":")[0],
        )
        desc += f"{rio_url} | {wcl_url}"

        embed = discord.Embed(
            description=desc,
            color=discord.Colour.green(),
        )

        guild_log_channel_id: int = await self.config.guild(guild).guild_log_welcome_channel()
        if not guild_log_channel_id:
            return
        guild_log_channel = guild.get_channel_or_thread(guild_log_channel_id)
        if not guild_log_channel:
            return

        if guild_log_channel.permissions_for(guild.me).embed_links:
            await guild_log_channel.send(
                embed=embed,
                silent=True,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False),
            )
        else:
            await guild_log_channel.send(
                content=desc,
                silent=True,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False),
            )

    async def get_event_embeds(self, difference, guild):
        embeds = []
        for diff in difference:
            if diff[0] == "add":
                await self.add_new_members(diff, embeds, guild)
            elif diff[0] == "change":
                await self.add_changed_members(diff, embeds, guild)
            elif diff[0] == "remove":
                await self.add_removed_members(diff, embeds, guild)
        return embeds

    async def add_new_members(self, diff, embeds: list, guild: discord.Guild) -> None:
        for member in diff[2]:
            member_name = member[0]
            member_rank_new = await self.get_rank_string(guild, member[1])

            embed = discord.Embed(
                title=_("**{member}** joined the guild as **{rank}**").format(
                    member=member_name, rank=member_rank_new
                ),
                description=await self.make_description(guild, member_name),
                color=discord.Colour.green(),
            )
            embeds.append(embed)

    async def add_changed_members(self, diff, embeds: list, guild: discord.Guild) -> None:
        member_name = diff[1]
        member_rank_old = await self.get_rank_string(guild, diff[2][0])
        member_rank_new = await self.get_rank_string(guild, diff[2][1])

        embed = discord.Embed(
            title=_("**{member}** was {changed} from **{old_rank}** to **{new_rank}**").format(
                member=member_name,
                old_rank=member_rank_old,
                new_rank=member_rank_new,
                changed=_("promoted") if diff[2][0] > diff[2][1] else _("demoted"),
            ),
            description=await self.make_description(guild, member_name),
            color=discord.Colour.blurple(),
        )
        embeds.append(embed)

    async def add_removed_members(self, diff, embeds: list, guild: discord.Guild) -> None:
        for member in diff[2]:
            member_name = member[0]
            member_rank_new = await self.get_rank_string(guild, member[1])

            embed = discord.Embed(
                title=_("**{member} ({rank})** left the guild").format(
                    member=member_name, rank=member_rank_new
                ),
                description=await self.make_description(guild, member_name),
                color=discord.Colour.red(),
            )
            embeds.append(embed)

    async def make_description(
        self,
        guild: discord.Guild,
        member_name: str,  # member_realm: str
    ) -> str:
        # region = await self.config.guild(guild).region()
        description = humanize_list(await self.guess_member(guild, member_name), style="or")
        # this is fucked
        # description += f"\n{self.get_raiderio_url(member_realm, region, member_name)} | "
        # description += f"{self.get_warcraftlogs_url(member_realm, region, member_name)}"
        return description

    async def guess_member(self, guild: discord.Guild, member_name: str) -> list[str]:
        """
        Guesses the Discord member based on their name using fuzzy string matching.

        :param guild: The Discord guild to search for the member in.
        :param member_name: The name of the character to search for.
        :return: A tuple containing mentions of the Discord members that match the character name.
        """
        choices: list[str] = []
        for member in guild.members:
            names = {member.display_name, member.name, member.nick}
            extract = process.extractOne(
                member_name,
                {name for name in names if name is not None},
                scorer=fuzz.WRatio,
                processor=self.custom_processor,
            )
            choices.append(extract[0])

        extract = process.extract(
            member_name,
            choices,
            scorer=fuzz.WRatio,
            limit=10,
            score_cutoff=80,
            processor=self.custom_processor,
        )
        return [guild.members[member[2]].mention for member in extract]

    @staticmethod
    def get_raiderio_url(realm: str, region: str, name: str) -> str:
        return (
            f"[Raider.io]"
            f"(https://raider.io/characters/{region.lower()}/{realm.lower()}/{name})"
        )

    @staticmethod
    def get_warcraftlogs_url(realm: str, region: str, name: str) -> str:
        return (
            f"[WarcraftLogs]"
            f"(https://www.warcraftlogs.com/character/{region.lower()}/{realm.lower()}/{name})"
        )

    @guild_log.error
    async def guild_log_error(self, error):
        log.error(f"Unhandled exception in guild_log task: {error}", exc_info=True)

    async def get_rank_string(self, guild: discord.Guild, rank: int) -> str:
        rank_strings: dict = await self.config.guild(guild).guild_rankstrings()
        return rank_strings.get(str(rank), f"Rank {rank}")

    @commands.group()
    @commands.guild_only()
    async def gmanage(self, ctx: commands.Context):
        """Guild management commands."""
        pass

    @gmanage.command(name="find")
    @commands.guild_only()
    async def gmanage_find(self, ctx: commands.Context, member_name: str):
        """Find a member in the guild."""
        msg = ""
        discord_members = await self.guess_member(ctx.guild, member_name)
        if discord_members:
            msg += f"Discord: {humanize_list(discord_members, style='or')}\n"

        member_name = member_name.title()
        try:
            ingame_members, rank = await self.guess_ingame_member(ctx.guild, member_name)
        except ValueError:
            ingame_members, rank = (None, None)
        except AttributeError:
            await ctx.send(
                _("Please use `{prefix}gmset` and set the name and realm of your guild.").format(
                    prefix=ctx.prefix
                )
            )
            return
        except InvalidBlizzardAPI:
            await ctx.send(
                _(
                    "The Blizzard API is not properly set up.\n"
                    "Create a client on https://develop.battle.net/ and then type in "
                    "`{prefix}set api blizzard client_id,whoops client_secret,whoops` "
                    "filling in `whoops` with your client's ID and secret."
                ).format(prefix=ctx.prefix)
            )
            return
        if ingame_members:
            msg += f"In-game: {humanize_list([member.split(':')[0] for member in ingame_members], style='or')}\nRank: {rank}\n"

            most_likely_member: str = ingame_members[0]
            rio_url: str = self.get_raiderio_url(
                realm=most_likely_member.split(":")[1],
                region=await self.config.guild(ctx.guild).region(),
                name=most_likely_member.split(":")[0],
            )
            wcl_url: str = self.get_warcraftlogs_url(
                realm=most_likely_member.split(":")[1],
                region=await self.config.guild(ctx.guild).region(),
                name=most_likely_member.split(":")[0],
            )
            msg += f"{rio_url} | {wcl_url}"

        if ctx.channel.permissions_for(ctx.guild.me).embed_links:
            embed = discord.Embed(
                description=msg or _("Nothing found."),
                color=await ctx.embed_color(),
            )
            await ctx.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False),
            )
        else:
            await ctx.send(content=msg or _("Nothing found."))

    async def guess_ingame_member(
        self, guild: discord.Guild, member_name: str
    ) -> tuple[list[str], str]:
        roster = await self.get_guild_roster(guild)
        name_mapping: dict[str, str] = {name.split(":")[0]: name for name in roster.keys()}
        extract = process.extract(
            member_name,
            set(name_mapping.keys()),
            scorer=fuzz.WRatio,
            limit=10,
            score_cutoff=80,
            processor=self.custom_processor,
        )
        extract.sort(key=lambda member: roster[name_mapping[member[0]]])
        ranks: list[int] = [roster[name_mapping[member[0]]] for member in extract]
        ingame_rank = await self.get_rank_string(guild, min(ranks))
        return [name_mapping[member[0]] for member in extract], ingame_rank

    def custom_processor(self, string: str) -> str:
        return "".join(
            string
            for string in unicodedata.normalize("NFD", string)
            if unicodedata.category(string) != "Mn"
        )
