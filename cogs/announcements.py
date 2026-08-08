import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.audit import log_action


class AnnouncementsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.channel.id in config.AUTO_REACT_CHANNEL_IDS:
            try:
                await message.add_reaction(config.AUTO_REACT_EMOJI)
            except Exception as e:
                import logging
                logging.error(f"تعذر إضافة التفاعل على الرسالة {message.id}: {e}")

    @app_commands.command(name="announce", description="إرسال رسالة كإعلان من البوت مع الإشارة إلى @everyone و @here")
    @app_commands.describe(
        message="نص الرسالة التي تريد أن يكتبها البوت",
        channel="القناة التي تريد الإرسال إليها (اختياري وتكون افتراضياً القناة الحالية)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def announce(self, interaction: discord.Interaction, message: str, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        await interaction.response.defer(ephemeral=True)

        content = f"@everyone @here\n{message}"

        try:
            await target_channel.send(content, allowed_mentions=discord.AllowedMentions(everyone=True))
            await log_action(self.bot, interaction.guild, interaction.user, "announce",
                              details=f"القناة: #{target_channel.name}")
            await interaction.followup.send(f"تم إرسال الإعلان بنجاح في القناة {target_channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"حدث خطأ أثناء إرسال الإعلان: {e}", ephemeral=True)

    @announce.error
    async def announce_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.followup.send("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnnouncementsCog(bot))
