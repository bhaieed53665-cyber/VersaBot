"""
سكربت لمرة واحدة: يعيد بناء جدول subs بقاعدة البيانات الجديدة (PostgreSQL)
اعتماداً على رسائل قناة اللوق (LOG_CHANNEL_ID) القديمة على ديسكورد.

كل رسالة لوق قديمة فيها 3 أسطر:
    اسم المشترك: <@USER_ID>
    مدة الاشتراك: <t:UNIX_TIMESTAMP:R>   (أو "انتهى الاشتراك" لو الاشتراك انتهى/انسحب)
    اسم الرتبة: <@&ROLE_ID>

السكربت بيقرأ كل الرسائل من الأقدم للأحدث، وبيسجل فقط الاشتراكات
اللي لسا "فعالة" (عندها طابع زمني)، وبيتجاهل اللي مكتوب فيها "انتهى".
لو نفس العضو/الرتبة تكررت بأكثر من رسالة (تجديد مثلاً)، آخر رسالة
(الأحدث) هي اللي بتفوز لأن save_sub بتعمل تحديث على نفس المفتاح.

الاستخدام:
    python rebuild_subs_from_log.py
"""

import asyncio
import re

import discord

import config
import database as db

LOG_LINE_1 = re.compile(r"المشترك\s*:\s*<@!?(\d+)>")
LOG_LINE_2_TIME = re.compile(r"الاشتراك\s*:\s*<t:(\d+):R>")
LOG_LINE_2_EXPIRED = re.compile(r"انتهى")
LOG_LINE_3 = re.compile(r"الرتب[ةه]\s*:\s*<@&(\d+)>")


async def main():
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.message_content = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            db.init_db()

            log_channel = client.get_channel(config.LOG_CHANNEL_ID)
            if log_channel is None:
                log_channel = await client.fetch_channel(config.LOG_CHANNEL_ID)

            guild = log_channel.guild
            print(f"جاري القراءة من قناة اللوق: {log_channel.name} بسيرفر {guild.name}")

            count_saved = 0
            count_skipped_expired = 0
            count_skipped_unparsed = 0

            # رموز اتجاه/تنسيق مخفية ممكن ديسكورد يحطها جوا النص العربي المختلط بالمنشنز
            INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")

            async for message in log_channel.history(limit=None, oldest_first=True):
                if not message.author.bot:
                    continue

                content = INVISIBLE_CHARS.sub("", message.content)

                m1 = LOG_LINE_1.search(content)
                m3 = LOG_LINE_3.search(content)

                if not m1 or not m3:
                    count_skipped_unparsed += 1
                    print(f"--- تعذر تحليل رسالة id={message.id} ---")
                    print(repr(content))
                    continue

                user_id = int(m1.group(1))
                role_id = int(m3.group(1))

                if LOG_LINE_2_EXPIRED.search(content):
                    count_skipped_expired += 1
                    continue

                m2 = LOG_LINE_2_TIME.search(content)
                if not m2:
                    count_skipped_unparsed += 1
                    continue

                end_timestamp = int(m2.group(1))
                import datetime
                end_date = datetime.datetime.fromtimestamp(end_timestamp, tz=datetime.timezone.utc)
                end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')

                # نستخدم وقت إرسال رسالة اللوق نفسها كتاريخ بداية تقريبي
                start_date_str = message.created_at.strftime('%Y-%m-%d %H:%M:%S')

                await asyncio.to_thread(
                    db.save_sub,
                    user_id, guild.id, role_id,
                    end_date_str,
                    None,          # dm_message_id غير معروف، هذا اختياري وما بيأثر
                    message.id,    # log_message_id - نفس رسالة اللوق حتى تنعدل لاحقاً عند الانتهاء
                    start_date_str
                )
                count_saved += 1

            print(f"تم حفظ {count_saved} اشتراك فعال.")
            print(f"تم تجاهل {count_skipped_expired} اشتراك منتهي/ملغي.")
            print(f"تم تجاهل {count_skipped_unparsed} رسالة غير مطابقة للصيغة.")
            print("اكتملت العملية ✅")

        finally:
            await client.close()

    await client.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
