"""
Cog: يحذف تلقائياً أي رسالة بدون صورة مرفقة بالقنوات المحددة بـ IMAGE_ONLY_CHANNEL_IDS
"""

import discord
from discord.ext import commands

from config import IMAGE_ONLY_CHANNEL_IDS


class ImageOnlyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # تجاهل رسائل البوتات
        if message.author.bot:
            return

        # تجاهل أي قناة مو ضمن القنوات المحددة
        if message.channel.id not in IMAGE_ONLY_CHANNEL_IDS:
            return

        # إذا فيه صورة مرفقة، خليها
        has_image = any(
            att.content_type and att.content_type.startswith("image/")
            for att in message.attachments
        )
        if has_image:
            return

        # حذف صامت بدون رسالة تنبيه
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ImageOnlyCog(bot))
