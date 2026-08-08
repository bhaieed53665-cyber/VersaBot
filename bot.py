import logging
import discord
from discord.ext import commands

import config
import database as db
from cogs.role_panel import RolePanelView

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # ضروري لتشغيل on_message (auto react)

INITIAL_EXTENSIONS = [
    "cogs.subscriptions",
    "cogs.role_panel",
    "cogs.announcements",
    "cogs.audit",
]


class SubscriptionBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # تسجيل الـ View الدائم لأزرار لوحة تحكم الرتبة، حتى تبقى فعّالة
        # بعد إعادة تشغيل البوت وليس فقط على الرسائل المُرسلة أثناء التشغيل الحالي
        self.add_view(RolePanelView(self))

        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)
            logging.info(f"تم تحميل الإضافة: {extension}")

        await self.tree.sync()
        logging.info("تمت مزامنة الأوامر الفورية بنجاح")


bot = SubscriptionBot()


@bot.event
async def on_ready():
    db.init_db()
    logging.info(f"تم تسجيل الدخول بنجاح باسم: {bot.user.name}")
    if config.AUTO_REACT_CHANNEL_IDS:
        logging.info(f"ميزة التفاعل التلقائي مفعّلة على القنوات: {config.AUTO_REACT_CHANNEL_IDS}")
    else:
        logging.warning("لم يتم تحديد أي قنوات لميزة التفاعل التلقائي لأن AUTO_REACT_CHANNEL_IDS فارغة.")


if __name__ == "__main__":
    if not config.TOKEN:
        raise SystemExit("خطأ: متغير البيئة DISCORD_TOKEN غير موجود.")
    bot.run(config.TOKEN)
