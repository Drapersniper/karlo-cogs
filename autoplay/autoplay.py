import logging
from typing import Optional

import discord
from pylav.players.player import Player
from pylav.players.query.obj import Query
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n

log = logging.getLogger("red.karlo-cogs.autoplay")
_ = Translator("AutoPlay", __file__)


@cog_i18n(_)
class AutoPlay(commands.Cog):
    """Automatically play music that a user is listening to on Spotify."""

    def __init__(self, bot):
        self.bot: Red = bot
        self.config = Config.get_conf(self, identifier=87446677010550784, force_registration=True)
        default_guild = {"tracked_member": None, "autoplaying": False}
        self.config.register_guild(**default_guild)

    @commands.command()
    @commands.guild_only()
    async def autoplay(self, ctx, member: discord.Member = None):
        """Set the member to track for autoplay."""
        if not self.bot.get_cog("PyLavPlayer"):
            await ctx.send(_("PyLavPlayer is not loaded."))
            return

        if member is None:
            await self.config.guild(ctx.guild).tracked_member.set(None)
            await ctx.send(_("No longer tracking any member."))
        else:
            await self.config.guild(ctx.guild).tracked_member.set(member.id)
            await ctx.send(
                _("I'll now play whatever {member} is listening to.").format(member=member.mention)
            )

    @commands.Cog.listener("on_presence_update")
    async def _on_presence_update(
        self, member_before: discord.Member, member_after: discord.Member
    ):
        if not self.bot.get_cog("PyLavPlayer"):
            return
        if await self._member_checks(member_after):
            return

        player: Player = self.bot.lavalink.get_player(member_after.guild.id)
        if player is None:
            log.debug("No player found.")
            return

        current_activity = self._get_spotify_activity(member_after)
        past_activity = self._get_spotify_activity(member_before)
        if not current_activity:
            autoplaying = await self.config.guild(member_after.guild).autoplaying()
            if autoplaying:
                await player.stop(member_after)
                await self.config.guild(member_after.guild).autoplaying.set(False)
            return
        if past_activity and past_activity.track_id == current_activity.track_id:
            return
        log.debug(f"Presence update detected. {current_activity.track_url}")

        query = await Query.from_string(current_activity.track_url)
        successful, count, failed = await self.bot.lavalink.get_all_tracks_for_queries(
            query, requester=member_after, player=player
        )
        if not successful:
            log.debug("No tracks found.")
            return
        await player.play(
            query=query,
            track=successful[0],
            requester=member_after,
        )
        await self.config.guild(member_after.guild).autoplaying.set(True)

    async def _member_checks(self, member: discord.Member) -> bool:
        """Check if the member is valid for autoplay."""
        return (
            member.id != tracked_member
            if (tracked_member := await self.config.guild(member.guild).tracked_member())
            else True
        )

    @staticmethod
    def _get_spotify_activity(member: discord.Member) -> Optional[discord.Spotify]:
        """Get the Spotify activity of a member."""
        return next(
            (
                activity
                for activity in member.activities
                if activity.type == discord.ActivityType.listening
                and hasattr(activity, "track_id")
                and hasattr(activity, "track_url")
            ),
            None,
        )

    def cog_unload(self):
        ...
