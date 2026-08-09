import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import config
import database as db
from utils import roles as role_utils
from utils.nsfw_check import is_image_nsfw


class RoleEditModal(discord.ui.Modal, title="تعديل الرتبة الخاصة"):
    name = discord.ui.TextInput(label="الاسم الجديد", required=False, max_length=100)

    def __init__(self, bot, role_id: int):
        super().__init__()
        self.bot = bot
        self.role_id = role_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        success, msg = await role_utils.do_edit_role(
            self.bot, interaction.guild, interaction.user, self.role_id,
            name=self.name.value or None,
        )
        await interaction.followup.send(msg, ephemeral=True)


class RemoveMemberSelect(discord.ui.Select):
    def __init__(self, bot, role_id: int, options: list[discord.SelectOption]):
        self.bot = bot
        self.role_id = role_id
        super().__init__(placeholder="اختر العضو الذي تريد سحب رتبتك منه", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target_id = int(self.values[0])
        success, msg = await role_utils.do_remove_shared_member(
            self.bot, interaction.guild, interaction.user, self.role_id, target_id
        )
        await interaction.followup.send(msg, ephemeral=True)


class AddMemberSelect(discord.ui.UserSelect):
    def __init__(self, bot, role_id: int):
        self.bot = bot
        self.role_id = role_id
        super().__init__(placeholder="اختر العضو الذي تريد إضافته إلى رتبتك الخاصة", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target = self.values[0]
        if isinstance(target, discord.User):
            try:
                target = await interaction.guild.fetch_member(target.id)
            except Exception:
                await interaction.followup.send("تعذر إيجاد هذا العضو في السيرفر.", ephemeral=True)
                return
        success, msg = await role_utils.do_add_shared_member(
            self.bot, interaction.guild, interaction.user, self.role_id, target
        )
        await interaction.followup.send(msg, ephemeral=True)


class RolePanelView(discord.ui.View):
    """View دائم (timeout=None) يُسجَّل مرة واحدة بـ setup_hook حتى تبقى الأزرار
    تعمل بعد إعادة تشغيل البوت."""

    def __init__(self, bot=None):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="إضافة عضو", style=discord.ButtonStyle.green, custom_id="role_panel_add")
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id, error = await role_utils.get_owner_single_role_id(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        view = discord.ui.View(timeout=120)
        view.add_item(AddMemberSelect(self.bot, role_id))
        await interaction.response.send_message("اختر العضو الذي تريد إضافته إلى رتبتك الخاصة:", view=view, ephemeral=True)

    @discord.ui.button(label="إزالة عضو", style=discord.ButtonStyle.red, custom_id="role_panel_remove")
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id, error = await role_utils.get_owner_single_role_id(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        shared_ids = await asyncio.to_thread(db.get_shared_members, interaction.user.id, interaction.guild.id, role_id)
        if not shared_ids:
            await interaction.response.send_message("لم تقم بإضافة أي عضو حتى الآن إلى رتبتك الخاصة", ephemeral=True)
            return

        options = []
        for member_id in shared_ids:
            member = interaction.guild.get_member(member_id)
            label = member.display_name if member else f"عضو مغادر ({member_id})"
            options.append(discord.SelectOption(label=label, value=str(member_id)))

        view = discord.ui.View(timeout=120)
        view.add_item(RemoveMemberSelect(self.bot, role_id, options))
        await interaction.response.send_message("اختر العضو الذي تريد سحب رتبتك منه:", view=view, ephemeral=True)

    @discord.ui.button(label="تعديل الرتبة", style=discord.ButtonStyle.blurple, custom_id="role_panel_edit")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id, error = await role_utils.get_owner_single_role_id(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(RoleEditModal(self.bot, role_id))

    @discord.ui.button(label="إزالة الأيقونة", style=discord.ButtonStyle.red, custom_id="role_panel_remove_icon")
    async def remove_icon_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id, error = await role_utils.get_owner_single_role_id(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        success, msg = await role_utils.do_remove_role_icon(self.bot, interaction.guild, interaction.user, role_id)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="رفع صورة كأيقونة", style=discord.ButtonStyle.blurple, custom_id="role_panel_upload_icon")
    async def upload_icon_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id, error = await role_utils.get_owner_single_role_id(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.send_message(
            "أرسل الصورة التي تريد استخدامها كأيقونة لرتبتك خلال 60 ثانية في هذه القناة "
            "(PNG أو JPG أو GIF، بحجم أقل من 256 كيلوبايت).",
            ephemeral=True
        )

        def check(m: discord.Message):
            return (
                m.author.id == interaction.user.id
                and m.channel.id == interaction.channel.id
                and len(m.attachments) > 0
            )

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await interaction.followup.send("انتهت المهلة، لم يتم استلام أي صورة.", ephemeral=True)
            return

        attachment = msg.attachments[0]
        if attachment.content_type not in ("image/png", "image/jpeg", "image/gif"):
            await interaction.followup.send("نوع الملف غير مدعوم. يرجى إرسال صورة PNG أو JPG أو GIF.", ephemeral=True)
            return

        try:
            image_bytes = await attachment.read()
        except Exception as e:
            await interaction.followup.send(f"تعذر تحميل الصورة: {e}", ephemeral=True)
            return

        # فحص الصورة عن وجود محتوى عري/غير لائق قبل قبولها
        is_nsfw, score = await is_image_nsfw(image_bytes)

        # نحذف الرسالة فوراً بمجرد ما نسحب بيانات الصورة منها، قبل ما نبلش نطبقها كأيقونة
        try:
            await msg.delete()
        except Exception:
            pass

        if is_nsfw:
            await interaction.followup.send(
                "❌ تم رفض هذه الصورة لأنها تحتوي على محتوى غير لائق. الرجاء اختيار صورة أخرى مناسبة.",
                ephemeral=True
            )
            return

        success, result_msg = await role_utils.do_edit_role(
            self.bot, interaction.guild, interaction.user, role_id, icon_bytes=image_bytes
        )
        await interaction.followup.send(result_msg, ephemeral=True)

    @discord.ui.button(label="مدة الاشتراك", style=discord.ButtonStyle.gray, custom_id="role_panel_duration")
    async def duration_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        import datetime
        info, error = await role_utils.get_owner_sub_info(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        role_id, start_date_str, end_date_str = info

        if start_date_str:
            start_dt = datetime.datetime.strptime(start_date_str, '%Y-%m-%d %H:%M:%S')
            start_text = f"{start_dt.month}/{start_dt.day}"
        else:
            start_text = "غير معروف"

        end_dt = datetime.datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
        end_timestamp = int(end_dt.timestamp())

        msg = (
            f"اسم المشترك: {interaction.user.mention}\n"
            f"موعد الاشتراك: {start_text}\n"
            f"الوقت المتبقي حتى نهاية الاشتراك: <t:{end_timestamp}:R>"
        )
        await interaction.response.send_message(msg, ephemeral=True)


class RolePanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="send_role_panel", description="نشر لوحة تحكم الرتبة الخاصة في قناة معينة")
    @app_commands.describe(channel="القناة التي تريد نشر اللوحة فيها (اختياري وتكون افتراضياً القناة الحالية)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def send_role_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="لوحة تحكم الرتب الخاصة",
            description=(
                "إضافة عضو: يمكنك إضافة شخصين إلى رتبتك\n"
                "إزالة عضو: إزالة رتبتك الخاصة من عضو أضفته سابقاً\n"
                "تعديل الرتبة: تعديل اسم الرتبة الخاصة\n"
                "إزالة الأيقونة: إزالة الأيقونة الحالية الموضوعة على رتبتك الخاصة\n"
                "رفع صورة كأيقونة: استخدام صورة من جهازك كأيقونة لرتبتك\n"
                "مدة الاشتراك: عرض تفاصيل اشتراكك والوقت المتبقي حتى انتهائه\n\n"
                f"ملاحظة: في حال رغبتك بلون جديد أو أيقونة خارجية خاصة بك يرجى التوجه إلى القناة "
                f"<#{config.TICKET_CHANNEL_ID}> والتواصل مع <@{config.ADMIN_USER_ID}>"
            ),
            color=discord.Color.blurple()
        )

        try:
            await target_channel.send(embed=embed, view=RolePanelView(self.bot))
            await interaction.followup.send(f"تم نشر اللوحة في القناة {target_channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"حدث خطأ أثناء نشر اللوحة: {e}", ephemeral=True)

    @app_commands.command(name="remove_member", description="سحب رتبتك من عضو إضافي كنت قد أضفته سابقاً")
    @app_commands.describe(member="العضو الذي تريد سحب رتبتك منه")
    async def remove_member(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        role_id, error = await role_utils.get_owner_single_role_id(interaction.guild.id, interaction.user.id)
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return
        success, msg = await role_utils.do_remove_shared_member(
            self.bot, interaction.guild, interaction.user, role_id, member.id
        )
        await interaction.followup.send(msg, ephemeral=True)

    @send_role_panel.error
    async def send_role_panel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.followup.send("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RolePanelCog(bot))
