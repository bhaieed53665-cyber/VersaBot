"""
دالة مركزية واحدة لتسجيل أي عملية حساسة. تُستدعى من كل الأكواج
بدل ما يتكرر كود التسجيل بكل دالة على حدة.
"""
import asyncio
import logging
import discord

import config
import database as db

ACTION_LABELS = {
    "add_sub": "إضافة اشتراك",
    "remove_sub": "إزالة اشتراك",
    "expire_sub": "انتهاء اشتراك تلقائي",
    "add_member": "إضافة عضو مشارك",
    "remove_member": "إزالة عضو مشارك",
    "edit_role": "تعديل الرتبة",
    "remove_icon": "إزالة أيقونة الرتبة",
    "announce": "إعلان",
}


async def log_action(bot: discord.Client, guild: discord.Guild, actor, action: str,
                      target_id: int = None, role_id: int = None, details: str = None):
    """
    actor: discord.Member/User أو None (مثلاً بالمهمة الدورية التلقائية)
    """
    actor_id = actor.id if actor else None
    actor_name = str(actor) if actor else "النظام (تلقائي)"

    await asyncio.to_thread(
        db.insert_audit_log,
        guild.id, actor_id, actor_name, action, target_id, role_id, details
    )

    if not config.AUDIT_CHANNEL_ID:
        return

    channel = guild.get_channel(config.AUDIT_CHANNEL_ID)
    if not channel:
        try:
            channel = await guild.fetch_channel(config.AUDIT_CHANNEL_ID)
        except Exception:
            return

    label = ACTION_LABELS.get(action, action)
    embed = discord.Embed(title=f"سجل تدقيق: {label}", color=discord.Color.orange())
    embed.add_field(name="المنفّذ", value=actor.mention if actor else "تلقائي (النظام)", inline=True)
    if target_id:
        embed.add_field(name="الهدف", value=f"<@{target_id}>", inline=True)
    if role_id:
        embed.add_field(name="الرتبة", value=f"<@&{role_id}>", inline=True)
    if details:
        embed.add_field(name="تفاصيل", value=details, inline=False)
    embed.timestamp = discord.utils.utcnow()

    try:
        await channel.send(embed=embed)
    except Exception as e:
        logging.error(f"تعذر إرسال سجل التدقيق إلى القناة: {e}")
