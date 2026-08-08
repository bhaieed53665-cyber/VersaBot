import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.audit import ACTION_LABELS

PAGE_SIZE = 10


def _build_embed(guild: discord.Guild, rows, page: int, total_pages: int, member_filter: discord.Member = None):
    title = "سجل التدقيق"
    if member_filter:
        title += f" — {member_filter.display_name}"

    embed = discord.Embed(title=title, color=discord.Color.dark_orange())

    if not rows:
        embed.description = "لا يوجد أي سجلات لعرضها."
        return embed

    lines = []
    for actor_id, actor_name, action, target_id, role_id, details, created_at in rows:
        label = ACTION_LABELS.get(action, action)
        actor_text = f"<@{actor_id}>" if actor_id else "تلقائي (النظام)"
        line = f"**{label}** — بواسطة {actor_text}"
        if target_id:
            line += f" على <@{target_id}>"
        if role_id:
            line += f" — الرتبة <@&{role_id}>"
        line += f"\n`{created_at} UTC`"
        if details:
            line += f" — {details}"
        lines.append(line)

    embed.description = "\n\n".join(lines)
    embed.set_footer(text=f"صفحة {page + 1} من {total_pages}")
    return embed


class AuditPaginationView(discord.ui.View):
    def __init__(self, guild: discord.Guild, member_filter: discord.Member = None, page: int = 0):
        super().__init__(timeout=120)
        self.guild = guild
        self.member_filter = member_filter
        self.page = page

    async def _refresh(self, interaction: discord.Interaction):
        member_id = self.member_filter.id if self.member_filter else None
        total = await asyncio.to_thread(db.count_audit_log, self.guild.id, member_id)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(0, min(self.page, total_pages - 1))

        rows = await asyncio.to_thread(
            db.get_audit_log, self.guild.id, member_id, PAGE_SIZE, self.page * PAGE_SIZE
        )
        embed = _build_embed(self.guild, rows, self.page, total_pages, self.member_filter)

        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= total_pages - 1

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="السابق", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="التالي", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self._refresh(interaction)


class AuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="audit_log", description="عرض سجل تدقيق العمليات (للإدارة فقط)")
    @app_commands.describe(member="فلترة السجل حسب عضو معيّن (اختياري)")
    @app_commands.checks.has_permissions(administrator=True)
    async def audit_log(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)

        member_id = member.id if member else None
        total = await asyncio.to_thread(db.count_audit_log, interaction.guild.id, member_id)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

        rows = await asyncio.to_thread(db.get_audit_log, interaction.guild.id, member_id, PAGE_SIZE, 0)
        embed = _build_embed(interaction.guild, rows, 0, total_pages, member)

        view = AuditPaginationView(interaction.guild, member, page=0)
        view.previous_page.disabled = True
        view.next_page.disabled = total_pages <= 1

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @audit_log.error
    async def audit_log_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.followup.send("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditCog(bot))
