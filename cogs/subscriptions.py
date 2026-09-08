import asyncio
import datetime
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import database as db
from utils import roles as role_utils
from utils.audit import log_action


def _format_duration(days: int, hours: int, minutes: int, seconds: int) -> str:
    """يبني نص وصفي للمدة الزمنية (يُستخدم بأكثر من أمر)."""
    time_parts = []
    if days > 0: time_parts.append(f"{days} يوم")
    if hours > 0: time_parts.append(f"{hours} ساعة")
    if minutes > 0: time_parts.append(f"{minutes} دقيقة")
    if seconds > 0: time_parts.append(f"{seconds} ثانية")
    return " و ".join(time_parts)


class SubscriptionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_expired_subscriptions.start()

    def cog_unload(self):
        self.check_expired_subscriptions.cancel()

    # -----------------------------------------------------------------
    # /add_sub
    # -----------------------------------------------------------------
    @app_commands.command(name="add_sub", description="إضافة اشتراك رتبة لعضو محدد")
    @app_commands.describe(
        member="العضو المراد إضافة الرتبة له",
        role="الرتبة المحددة",
        days="عدد الأيام",
        hours="عدد الساعات",
        minutes="عدد الدقائق",
        seconds="عدد الثواني"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_sub(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role,
                       days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
        await interaction.response.defer()

        if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            await interaction.followup.send("يرجى تحديد مدة زمنية واحدة على الأقل من أيام أو ساعات أو دقائق أو ثوانٍ.")
            return

        if interaction.guild.me.top_role <= role:
            await interaction.followup.send("لا يمكنني منح هذه الرتبة. يرجى رفع رتبة البوت فوق الرتبة المراد منحها في إعدادات السيرفر.")
            return

        start_date = datetime.datetime.now(datetime.timezone.utc)
        end_date = start_date + datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        end_timestamp = int(end_date.timestamp())
        start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')

        dm_msg_id = None
        log_msg_id = None
        dm_sent = True

        try:
            await member.add_roles(role)
            await role_utils.grant_subscribers_channel_access(interaction.guild, member)

            dm_text = f"تم اشتراكك في الرتبة الخاصة ({role.name}) وموعد انتهاء اشتراكك هو: <t:{end_timestamp}:R>"
            if config.VIP_CHANNEL_ID:
                dm_text += f"\n\nيمكنك التحكم برتبتك الخاصة من خلال تعديل الاسم أو وضع أيقونة وإضافة أو إزالة الأعضاء من القناة: <#{config.VIP_CHANNEL_ID}>"
            try:
                sent_msg = await member.send(dm_text)
                dm_msg_id = sent_msg.id
            except Exception:
                dm_sent = False

            if config.LOG_CHANNEL_ID:
                log_channel = interaction.guild.get_channel(config.LOG_CHANNEL_ID) or await self.bot.fetch_channel(config.LOG_CHANNEL_ID)
                if log_channel:
                    log_msg_text = (
                        f"اسم المشترك: {member.mention}\n"
                        f"مدة الاشتراك: <t:{end_timestamp}:R>\n"
                        f"اسم الرتبة: {role.mention}"
                    )
                    try:
                        sent_log_msg = await log_channel.send(log_msg_text)
                        log_msg_id = sent_log_msg.id
                    except Exception as e:
                        logging.error(f"تعذر الإرسال إلى قناة المشتركين: {e}")

            await asyncio.to_thread(
                db.save_sub, member.id, interaction.guild.id, role.id,
                end_date_str, dm_msg_id, log_msg_id, start_date_str
            )

            await log_action(
                self.bot, interaction.guild, interaction.user, "add_sub",
                target_id=member.id, role_id=role.id,
                details=f"ينتهي: {end_date_str} UTC"
            )

            duration_text = _format_duration(days, hours, minutes, seconds)

            msg = (
                f"تمت إضافة الرتبة {role.mention} للعضو {member.mention} لمدة: {duration_text}\n"
                f"موعد الانتهاء: <t:{end_timestamp}:R>"
            )
            if not dm_sent:
                msg += "\n*(تنبيه: لم أتمكن من إرسال رسالة خاصة للعضو لأن الرسائل الخاصة لديه مغلقة)*"

            await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send(f"حدث خطأ أثناء منح الرتبة: {e}")

    # -----------------------------------------------------------------
    # /renew_sub - تجديد اشتراك موجود (يزيد المدة فوق تاريخ الانتهاء الحالي
    # ويرسل رسالة خاصة جديدة للعضو تأكيد التجديد)
    # -----------------------------------------------------------------
    @app_commands.command(name="renew_sub", description="تجديد اشتراك رتبة موجود لعضو (يزيد المدة على الاشتراك الحالي)")
    @app_commands.describe(
        member="العضو صاحب الاشتراك المراد تجديده",
        role="الرتبة المحددة",
        days="عدد الأيام المضافة",
        hours="عدد الساعات المضافة",
        minutes="عدد الدقائق المضافة",
        seconds="عدد الثواني المضافة"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def renew_sub(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role,
                         days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
        await interaction.response.defer()

        if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            await interaction.followup.send("يرجى تحديد مدة زمنية واحدة على الأقل من أيام أو ساعات أو دقائق أو ثوانٍ.")
            return

        row = await asyncio.to_thread(db.get_sub, member.id, interaction.guild.id, role.id)
        if not row:
            await interaction.followup.send(
                "لا يوجد اشتراك فعال حالياً لهذا العضو بهذه الرتبة. استخدم أمر /add_sub لإضافة اشتراك جديد."
            )
            return

        current_end_str, dm_msg_id, log_msg_id, _start_date_str = row
        current_end_dt = datetime.datetime.strptime(current_end_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        base_dt = max(current_end_dt, now)

        new_end_dt = base_dt + datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        new_end_str = new_end_dt.strftime('%Y-%m-%d %H:%M:%S')
        new_end_timestamp = int(new_end_dt.timestamp())

        try:
            if interaction.guild.me.top_role <= role:
                await interaction.followup.send("لا يمكنني التأكد من صلاحيات الرتبة. يرجى رفع رتبة البوت فوق الرتبة المراد تجديدها في إعدادات السيرفر.")
                return

            if role not in member.roles:
                await member.add_roles(role)
                await role_utils.grant_subscribers_channel_access(interaction.guild, member)

            await asyncio.to_thread(db.update_sub_end_date, member.id, interaction.guild.id, role.id, new_end_str)

            if log_msg_id and config.LOG_CHANNEL_ID:
                try:
                    log_channel = interaction.guild.get_channel(config.LOG_CHANNEL_ID) or await self.bot.fetch_channel(config.LOG_CHANNEL_ID)
                    if log_channel:
                        log_msg = await log_channel.fetch_message(log_msg_id)
                        await log_msg.edit(content=(
                            f"اسم المشترك: {member.mention}\n"
                            f"مدة الاشتراك: <t:{new_end_timestamp}:R>\n"
                            f"اسم الرتبة: {role.mention}"
                        ))
                except Exception as e:
                    logging.error(f"تعذر تعديل رسالة شات المشتركين عند التجديد: {e}")

            dm_sent = True
            try:
                await member.send(
                    f"تم تجديد اشتراكك في الرتبة الخاصة ({role.name})، وموعد انتهاء اشتراكك الجديد هو: <t:{new_end_timestamp}:R>"
                )
            except Exception:
                dm_sent = False

            await log_action(
                self.bot, interaction.guild, interaction.user, "renew_sub",
                target_id=member.id, role_id=role.id,
                details=f"ينتهي الآن: {new_end_str} UTC"
            )

            duration_text = _format_duration(days, hours, minutes, seconds)
            msg = (
                f"تم تجديد اشتراك {role.mention} للعضو {member.mention} لمدة إضافية: {duration_text}\n"
                f"موعد الانتهاء الجديد: <t:{new_end_timestamp}:R>"
            )
            if not dm_sent:
                msg += "\n*(تنبيه: لم أتمكن من إرسال رسالة خاصة للعضو لأن الرسائل الخاصة لديه مغلقة)*"

            await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send(f"حدث خطأ أثناء تجديد الاشتراك: {e}")

    # -----------------------------------------------------------------
    # /add_sub_time - تصحيح/زيادة مدة اشتراك موجود بدون إشعار العضو
    # -----------------------------------------------------------------
    @app_commands.command(name="add_sub_time", description="زيادة مدة اشتراك موجود (تصحيح) بدون إشعار العضو")
    @app_commands.describe(
        member="العضو صاحب الاشتراك",
        role="الرتبة المحددة",
        days="عدد الأيام المضافة",
        hours="عدد الساعات المضافة",
        minutes="عدد الدقائق المضافة",
        seconds="عدد الثواني المضافة"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_sub_time(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role,
                            days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
        await interaction.response.defer(ephemeral=True)

        if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
            await interaction.followup.send("يرجى تحديد مدة زمنية واحدة على الأقل من أيام أو ساعات أو دقائق أو ثوانٍ.", ephemeral=True)
            return

        row = await asyncio.to_thread(db.get_sub, member.id, interaction.guild.id, role.id)
        if not row:
            await interaction.followup.send(
                "لا يوجد اشتراك فعال حالياً لهذا العضو بهذه الرتبة. استخدم أمر /add_sub لإضافة اشتراك جديد.",
                ephemeral=True
            )
            return

        current_end_str, _dm_msg_id, log_msg_id, _start_date_str = row
        current_end_dt = datetime.datetime.strptime(current_end_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        base_dt = max(current_end_dt, now)

        new_end_dt = base_dt + datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        new_end_str = new_end_dt.strftime('%Y-%m-%d %H:%M:%S')
        new_end_timestamp = int(new_end_dt.timestamp())

        try:
            await asyncio.to_thread(db.update_sub_end_date, member.id, interaction.guild.id, role.id, new_end_str)

            if log_msg_id and config.LOG_CHANNEL_ID:
                try:
                    log_channel = interaction.guild.get_channel(config.LOG_CHANNEL_ID) or await self.bot.fetch_channel(config.LOG_CHANNEL_ID)
                    if log_channel:
                        log_msg = await log_channel.fetch_message(log_msg_id)
                        await log_msg.edit(content=(
                            f"اسم المشترك: {member.mention}\n"
                            f"مدة الاشتراك: <t:{new_end_timestamp}:R>\n"
                            f"اسم الرتبة: {role.mention}"
                        ))
                except Exception as e:
                    logging.error(f"تعذر تعديل رسالة شات المشتركين عند زيادة المدة: {e}")

            await log_action(
                self.bot, interaction.guild, interaction.user, "add_sub_time",
                target_id=member.id, role_id=role.id,
                details=f"ينتهي الآن: {new_end_str} UTC"
            )

            duration_text = _format_duration(days, hours, minutes, seconds)
            await interaction.followup.send(
                f"تمت إضافة {duration_text} على اشتراك {role.mention} للعضو {member.mention} (بدون إشعاره).\n"
                f"موعد الانتهاء الجديد: <t:{new_end_timestamp}:R>",
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(f"حدث خطأ أثناء زيادة مدة الاشتراك: {e}", ephemeral=True)

    # -----------------------------------------------------------------
    # /remove_sub
    # -----------------------------------------------------------------
    @app_commands.command(name="remove_sub", description="إزالة اشتراك رتبة من عضو")
    @app_commands.describe(member="العضو المراد سحب الرتبة منه", role="الرتبة المراد سحبها")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_sub(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        await interaction.response.defer()

        row = await asyncio.to_thread(db.get_and_delete_sub, member.id, interaction.guild.id, role.id)

        try:
            if role in member.roles:
                await member.remove_roles(role)

            await role_utils.cleanup_shared_members(self.bot, interaction.guild, member.id, role.id)
            await role_utils.revoke_subscribers_channel_access(interaction.guild, member.id)

            if row:
                dm_msg_id, log_msg_id = row[0], row[1]

                if dm_msg_id:
                    try:
                        dm_channel = member.dm_channel or await member.create_dm()
                        msg = await dm_channel.fetch_message(dm_msg_id)
                        await msg.edit(content=f"تم اشتراكك في الرتبة الخاصة ({role.name}) وموعد انتهاء اشتراكك: انتهى")
                    except Exception:
                        pass

                if log_msg_id and config.LOG_CHANNEL_ID:
                    try:
                        log_channel = interaction.guild.get_channel(config.LOG_CHANNEL_ID) or await self.bot.fetch_channel(config.LOG_CHANNEL_ID)
                        if log_channel:
                            log_msg = await log_channel.fetch_message(log_msg_id)
                            await log_msg.edit(content=f"اسم المشترك: {member.mention}\nمدة الاشتراك: انتهى الاشتراك\nاسم الرتبة: {role.mention}")
                    except Exception as e:
                        logging.error(f"تعذر تعديل رسالة شات المشتركين: {e}")

            try:
                await member.send(
                    f"تنبيه: انتهى اشتراك الرتبة الخاصة. في حال رغبتك بالاشتراك مرة أخرى يرجى فتح تذكرة في القناة "
                    f"<#{config.TICKET_CHANNEL_ID}> والتواصل مع <@{config.ADMIN_USER_ID}>"
                )
            except Exception:
                pass

            await log_action(self.bot, interaction.guild, interaction.user, "remove_sub",
                              target_id=member.id, role_id=role.id)

            await interaction.followup.send(f"تمت إزالة الرتبة {role.mention} وسحب الاشتراك من العضو {member.mention} بنجاح.")

        except Exception as e:
            await interaction.followup.send(f"حدث خطأ أثناء إزالة الرتبة: {e}")

    @add_sub.error
    async def add_sub_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_admin_error(interaction, error)

    @renew_sub.error
    async def renew_sub_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_admin_error(interaction, error)

    @add_sub_time.error
    async def add_sub_time_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_admin_error(interaction, error)

    @remove_sub.error
    async def remove_sub_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_admin_error(interaction, error)

    @staticmethod
    async def _handle_admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
            else:
                await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)

    # -----------------------------------------------------------------
    # المهمة الدورية: فحص الاشتراكات المنتهية كل دقيقة
    # -----------------------------------------------------------------
    @tasks.loop(minutes=1)
    async def check_expired_subscriptions(self):
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        expired = await asyncio.to_thread(db.get_expired_subs, now_str)
        if not expired:
            return

        to_delete = []

        for user_id, guild_id, role_id, dm_message_id, log_message_id in expired:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                try:
                    guild = await self.bot.fetch_guild(guild_id)
                except Exception:
                    continue

            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None

            role = guild.get_role(role_id)

            if member and role:
                if role in member.roles:
                    try:
                        await member.remove_roles(role)
                    except Exception as e:
                        logging.error(f"تعذر سحب الرتبة من {member.id}: {e}")

                await role_utils.cleanup_shared_members(self.bot, guild, user_id, role_id)
                await role_utils.revoke_subscribers_channel_access(guild, user_id)

                if dm_message_id:
                    try:
                        dm_channel = member.dm_channel or await member.create_dm()
                        old_dm_msg = await dm_channel.fetch_message(dm_message_id)
                        await old_dm_msg.edit(content=f"تم اشتراكك في الرتبة الخاصة ({role.name}) وموعد انتهاء اشتراكك: انتهى")
                    except Exception as e:
                        logging.error(f"تعذر تعديل رسالة الخاص القديمة: {e}")

                if log_message_id and config.LOG_CHANNEL_ID:
                    try:
                        log_channel = guild.get_channel(config.LOG_CHANNEL_ID) or await self.bot.fetch_channel(config.LOG_CHANNEL_ID)
                        if log_channel:
                            old_log_msg = await log_channel.fetch_message(log_message_id)
                            await old_log_msg.edit(content=f"اسم المشترك: {member.mention}\nمدة الاشتراك: انتهى الاشتراك\nاسم الرتبة: {role.mention}")
                    except Exception as e:
                        logging.error(f"تعذر تعديل رسالة شات المشتركين: {e}")

                try:
                    await member.send(
                        f"تنبيه: انتهى اشتراك الرتبة الخاصة. في حال رغبتك بالاشتراك مرة أخرى يرجى فتح تذكرة في القناة "
                        f"<#{config.TICKET_CHANNEL_ID}> والتواصل مع <@{config.ADMIN_USER_ID}>"
                    )
                except Exception:
                    logging.info(f"لم نتمكن من إرسال رسالة خاصة للعضو {member.id}")

                await log_action(self.bot, guild, None, "expire_sub", target_id=user_id, role_id=role_id)

            to_delete.append((user_id, guild_id, role_id))

        if to_delete:
            await asyncio.to_thread(db.delete_subs_bulk, to_delete)

    @check_expired_subscriptions.before_loop
    async def before_check_expired(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(SubscriptionsCog(bot))
