"""
كوج "صور فقط": يراقب القنوات المحددة بـ IMAGE_ONLY_CHANNEL_IDS.
أي رسالة تُرسل بهاي القنوات وما فيها صورة مرفقة (attachment) بتنحذف تلقائياً وفوراً،
مع إرسال تنبيه قصير للعضو يوضح إنو القناة مخصصة للصور فقط.
"""
import logging
import discord
from discord.ext import commands

import config

IMAGE_CONTENT_TYPES = ("image/",)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".heic")


def _has_image_attachment(message: discord.Message) -> bool:
    for attachment in message.attachments:
        content_type = (attachment.content_type or "").lower()
        if content_type.startswith(IMAGE_CONTENT_TYPES):
            return True
        if attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
            return True
    return False


class ImageOnlyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # تجاهل رسائل البوتات (منها هالبوت نفسه) حتى ما يحذف تنبيهاته أو رسائل بوتات ثانية
        if message.author.bot:
            return

        if message.channel.id not in config.IMAGE_ONLY_CHANNEL_IDS:
            return

        if _has_image_attachment(message):
            return

        try:
            await message.delete()
        except discord.Forbidden:
            logging.error(
                f"لا توجد صلاحية لحذف الرسالة {message.id} بالقناة {message.channel.id}. "
                "تأكد إنو البوت عندو صلاحية 'Manage Messages' بهاي القناة."
            )
            return
        except discord.NotFound:
            return
        except Exception as e:
            logging.error(f"تعذر حذف الرسالة {message.id} بقناة الصور فقط: {e}")
            return

        try:
            warning = await message.channel.send(
                f"{message.author.mention} هاي القناة مخصصة لإرسال الصور فقط 📷",
                delete_after=config.IMAGE_ONLY_WARNING_DELETE_AFTER,
            )
        except Exception as e:
            logging.error(f"تعذر إرسال رسالة التنبيه بقناة الصور فقط: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ImageOnlyCog(bot))
