"""
دوال مساعدة مشتركة تخص الرتب الخاصة وقناة كبار المشتركين (VIP).
تُستخدم من أكثر من Cog واحد لذلك وُضعت هنا بدل تكرارها.
"""
import asyncio
import logging
import re
import discord
import aiohttp

import config
import database as db
from utils.audit import log_action
from utils.content_filter import contains_profanity

MAX_SHARED_MEMBERS = config.MAX_SHARED_MEMBERS

# يطابق صيغة الإيموجي المخصص من السيرفر: <:name:id> أو المتحرك <a:name:id>
CUSTOM_EMOJI_RE = re.compile(r'^<a?:\w+:\d+>$')

# محارف غير مرئية (اتجاه النص Bidi، فراغ بعرض صفري..) قد تنسخ مع الإيموجي
# من لوحات مفاتيح أو تطبيقات معينة وتسبب رفض ديسكورد للإيموجي رغم أنه سليم بالعين المجردة
_INVISIBLE_CHARS = (
    '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2066', '\u2067', '\u2068', '\u2069', '\ufeff',
)


def _sanitize_emoji_text(value: str) -> str:
    for ch in _INVISIBLE_CHARS:
        value = value.replace(ch, '')
    return value.strip()


async def grant_subscribers_channel_access(guild: discord.Guild, member: discord.Member):
    if not config.VIP_CHANNEL_ID:
        return
    channel = guild.get_channel(config.VIP_CHANNEL_ID)
    if not channel:
        try:
            channel = await guild.fetch_channel(config.VIP_CHANNEL_ID)
        except Exception:
            return
    try:
        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            reason="منح صلاحية مشاهدة قناة كبار المشتركين عند الاشتراك"
        )
    except Exception as e:
        logging.error(f"تعذر منح صلاحية قناة كبار المشتركين للعضو {member.id}: {e}")


async def revoke_subscribers_channel_access(guild: discord.Guild, member_id: int):
    if not config.VIP_CHANNEL_ID:
        return
    channel = guild.get_channel(config.VIP_CHANNEL_ID)
    if not channel:
        try:
            channel = await guild.fetch_channel(config.VIP_CHANNEL_ID)
        except Exception:
            return
    member = guild.get_member(member_id)
    if not member:
        try:
            member = await guild.fetch_member(member_id)
        except Exception:
            return
    try:
        await channel.set_permissions(
            member, overwrite=None,
            reason="سحب صلاحية قناة كبار المشتركين بعد انتهاء الاشتراك أو إلغائه"
        )
    except Exception as e:
        logging.error(f"تعذر سحب صلاحية قناة كبار المشتركين من العضو {member_id}: {e}")


async def cleanup_shared_members(bot, guild: discord.Guild, owner_id: int, role_id: int):
    shared_ids = await asyncio.to_thread(db.get_shared_members, owner_id, guild.id, role_id)
    if not shared_ids:
        return

    role = guild.get_role(role_id)

    for member_id in shared_ids:
        member = guild.get_member(member_id)
        if not member:
            try:
                member = await guild.fetch_member(member_id)
            except Exception:
                member = None

        if member and role and role in member.roles:
            try:
                await member.remove_roles(role)
            except Exception as e:
                logging.error(f"تعذر سحب الرتبة المشتركة من {member_id}: {e}")

        await revoke_subscribers_channel_access(guild, member_id)

        if member:
            try:
                await member.send(
                    f"تنبيه: تم سحب رتبتك ({role.name if role else role_id}) "
                    f"لأن اشتراك صاحب الرتبة الأساسي قد انتهى أو أُلغي."
                )
            except Exception:
                pass

    await asyncio.to_thread(db.delete_shared_members_for_role, owner_id, guild.id, role_id)


async def get_owner_single_role_id(guild_id: int, user_id: int):
    role_ids = await asyncio.to_thread(db.get_owner_role_ids, guild_id, user_id)
    if not role_ids:
        return None, "لا يوجد لديك أي اشتراك فعال حالياً. هذه الميزة مخصصة للمشتركين فقط."
    if len(role_ids) > 1:
        return None, "لديك أكثر من رتبة اشتراك فعالة في الوقت نفسه. يرجى التواصل مع الإدارة لتحديد الرتبة المقصودة بالضبط."
    return role_ids[0], None


async def get_owner_sub_info(guild_id: int, user_id: int):
    rows = await asyncio.to_thread(db.get_owner_sub_info, guild_id, user_id)
    if not rows:
        return None, "لا يوجد لديك أي اشتراك فعال حالياً. هذه الميزة مخصصة للمشتركين فقط."
    if len(rows) > 1:
        return None, "لديك أكثر من رتبة اشتراك فعالة في الوقت نفسه. يرجى التواصل مع الإدارة لتحديد الرتبة المقصودة بالضبط."
    return rows[0], None


async def do_add_shared_member(bot, guild: discord.Guild, owner: discord.Member, role_id: int, target: discord.Member):
    if target.bot:
        return False, "لا يمكنك إضافة بوت."
    if target.id == owner.id:
        return False, "لا يمكنك إضافة نفسك لأنك أساساً صاحب الرتبة."

    role = guild.get_role(role_id)
    if not role:
        return False, "لم يتم العثور على الرتبة. من المحتمل أنها حُذفت من السيرفر."
    if role in target.roles:
        return False, f"العضو {target.mention} يمتلك هذه الرتبة أساساً."

    shared_count, already_added = await asyncio.to_thread(
        db.check_shared_member_slot, owner.id, guild.id, role_id, target.id
    )
    if already_added:
        return False, f"العضو {target.mention} مضاف أساساً إلى رتبتك."
    if shared_count >= MAX_SHARED_MEMBERS:
        return False, f"لقد بلغت الحد الأقصى ({MAX_SHARED_MEMBERS}) من الأعضاء الإضافيين على رتبتك."
    if guild.me.top_role <= role:
        return False, "لا يمكن منح هذه الرتبة. يجب أن تكون رتبة البوت أعلى منها في إعدادات السيرفر."

    try:
        await target.add_roles(role, reason=f"تمت الإضافة بواسطة صاحب الرتبة {owner} (ID: {owner.id})")
    except discord.Forbidden:
        return False, "لا تتوفر لدي صلاحية كافية لمنح هذه الرتبة."
    except Exception as e:
        return False, f"حدث خطأ أثناء الإضافة: {e}"

    await asyncio.to_thread(db.add_shared_member, owner.id, guild.id, role_id, target.id)
    await grant_subscribers_channel_access(guild, target)

    await log_action(bot, guild, owner, "add_member", target_id=target.id, role_id=role_id)

    try:
        await target.send(
            f"تمت إضافتك إلى الرتبة ({role.name}) من قِبل {owner.mention}. "
            f"ملاحظة: ستُسحب هذه الرتبة منك تلقائياً في حال انتهاء اشتراك صاحب الرتبة الأساسي."
        )
    except Exception:
        pass

    return True, f"تمت إضافة {target.mention} إلى رتبتك الخاصة {role.mention} بنجاح"


async def do_remove_shared_member(bot, guild: discord.Guild, owner: discord.Member, role_id: int, target_id: int):
    existed = await asyncio.to_thread(db.remove_shared_member, owner.id, guild.id, role_id, target_id)
    if not existed:
        return False, "هذا العضو غير مضاف من طرفك أساساً."

    role = guild.get_role(role_id)
    member = guild.get_member(target_id)
    if member and role and role in member.roles:
        try:
            await member.remove_roles(role, reason=f"تمت الإزالة بواسطة صاحب الرتبة {owner} (ID: {owner.id})")
        except Exception as e:
            logging.error(f"تعذر سحب الرتبة من {target_id}: {e}")

    await revoke_subscribers_channel_access(guild, target_id)
    await log_action(bot, guild, owner, "remove_member", target_id=target_id, role_id=role_id)

    mention = member.mention if member else f"<@{target_id}>"
    return True, f"تم سحب رتبتك من {mention} بنجاح."


def _parse_hex_colour(value: str):
    return discord.Colour(int(value.lstrip('#'), 16))


def _build_gradient_colours(c1: discord.Colour, c2: discord.Colour):
    RoleColours = getattr(discord, 'RoleColours', None)
    if RoleColours is None:
        return None
    for kwargs in (
        {'primary': c1, 'secondary': c2},
        {'primary_colour': c1, 'secondary_colour': c2},
        {'primary_color': c1, 'secondary_color': c2},
    ):
        try:
            return RoleColours(**kwargs)
        except TypeError:
            continue
    return None


async def do_edit_role(bot, guild: discord.Guild, owner: discord.Member, role_id: int,
                        name=None, color=None, color2=None, emoji=None, icon_bytes=None):
    role = guild.get_role(role_id)
    if not role:
        return False, "لم يتم العثور على الرتبة. من المحتمل أنها حُذفت من السيرفر."
    if role not in owner.roles:
        return False, "لا تمتلك هذه الرتبة حالياً في حسابك."
    if guild.me.top_role <= role:
        return False, "لا يمكن تعديل هذه الرتبة. يجب أن تكون رتبة البوت أعلى منها في إعدادات السيرفر."

    edit_kwargs = {}
    if name:
        is_clean, _matched = contains_profanity(name)
        if not is_clean:
            return False, "لا يمكنك استخدام هذا الاسم لأنه يحتوي على لفظ غير لائق. الرجاء اختيار اسم آخر."
        edit_kwargs['name'] = name

    if color:
        try:
            c1 = _parse_hex_colour(color)
        except ValueError:
            return False, "صيغة اللون الأول غير صحيحة. استخدم صيغة hex مثل #ff0000."

        if color2:
            try:
                c2 = _parse_hex_colour(color2)
            except ValueError:
                return False, "صيغة اللون الثاني غير صحيحة. استخدم صيغة hex مثل #0000ff."
            gradient = _build_gradient_colours(c1, c2)
            if gradient is not None:
                edit_kwargs['colours'] = gradient
            else:
                edit_kwargs['colour'] = c1
        else:
            edit_kwargs['colour'] = c1
    elif color2:
        return False, "يجب تحديد اللون الأول قبل اللون الثاني."

    if emoji or icon_bytes:
        # ميزة أيقونة الرتبة (سواء إيموجي أو صورة) تتطلب مستوى تعزيز 2 على الأقل
        # نتحقق مسبقاً بدل ما ننتظر خطأ مبهم من ديسكورد
        if guild.premium_tier < 2:
            return False, (
                "ميزة أيقونة الرتبة تتطلب وصول السيرفر إلى مستوى تعزيز (Boost) 2 على الأقل. "
                f"مستوى السيرفر الحالي: {guild.premium_tier}."
            )

    if icon_bytes:
        # صورة مرفوعة مباشرة (من زر رفع صورة) - لها الأولوية
        edit_kwargs['display_icon'] = icon_bytes
    elif emoji:
        emoji = _sanitize_emoji_text(emoji)
        if not emoji:
            return False, "يرجى إدخال رمز تعبيري صالح."

        if CUSTOM_EMOJI_RE.match(emoji):
            # إيموجي مخصص من أحد السيرفرات - الـ API لا يقبله كنص
            # لذلك نحمّل صورته الفعلية ونستخدمها كأيقونة صورة بدل ذلك.
            # ملاحظة: PartialEmoji.from_str() ينشئ كائن غير مرتبط بأي اتصال فعلي بالبوت
            # (Invalid state (no ConnectionState provided)) لذلك نحمّل الصورة يدوياً عبر رابط CDN مباشرة.
            partial = discord.PartialEmoji.from_str(emoji)
            ext = "gif" if partial.animated else "png"
            cdn_url = f"https://cdn.discordapp.com/emojis/{partial.id}.{ext}"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(cdn_url, timeout=15) as resp:
                        if resp.status == 404:
                            return False, "تعذر إيجاد هذا الإيموجي، من المحتمل أنه محذوف."
                        if resp.status != 200:
                            return False, f"تعذر تحميل صورة الإيموجي المخصص (رمز الحالة: {resp.status})."
                        downloaded = await resp.read()
            except Exception as e:
                return False, f"تعذر تحميل صورة الإيموجي المخصص: {e}"
            edit_kwargs['display_icon'] = downloaded
        else:
            # لو المستخدم كتب شورت-كود نصي مثل :fire: بدل إيموجي حقيقي
            if re.match(r'^:[a-zA-Z0-9_+\-]+:$', emoji):
                return False, (
                    "يبدو أنك كتبت اسم الإيموجي كنص (مثل :fire:) بدل الرمز التعبيري الفعلي.\n"
                    "الرجاء إرسال الإيموجي نفسه (يمكنك نسخه ولصقه)، سواء كان إيموجي عادي أو إيموجي مخصص من هذا السيرفر."
                )
            # طول غير معقول يعني على الأغلب مو إيموجي (نص عادي بالغلط مثلاً)
            if len(emoji) > 20:
                return False, "الرجاء إرسال إيموجي واحد فقط وليس نصاً."
            # إيموجي يونيكود عادي (من داخل أو خارج السيرفر) - يُرسل مباشرة إلى ديسكورد.
            # يتطلب مستوى تعزيز 2 على الأقل (تم التحقق منه أعلاه)، وديسكورد نفسه بيرفض أي رمز غير صالح.
            edit_kwargs['display_icon'] = emoji

    if not edit_kwargs:
        return False, "يجب تحديد عنصر واحد على الأقل تريد تغييره."

    try:
        await role.edit(reason=f"تخصيص رتبة بواسطة {owner} (ID: {owner.id})", **edit_kwargs)
        await log_action(bot, guild, owner, "edit_role", target_id=owner.id, role_id=role_id,
                          details=", ".join(edit_kwargs.keys()))
        return True, f"تم تحديث رتبتك {role.mention} بنجاح."
    except discord.Forbidden:
        return False, "لا تتوفر لدي صلاحية كافية لتعديل هذه الرتبة."
    except discord.HTTPException as e:
        err_text = str(e).lower()
        if 'unknown emoji' in err_text:
            return False, (
                "لم يتم التعرف على الرمز التعبيري. تأكد أنك تستخدم إيموجي يونيكود عادي "
                "(وليس إيموجي مخصص من السيرفر)."
            )
        if 'icon' in err_text:
            return False, "تعذر تعيين الأيقونة. تتطلب هذه الميزة وصول السيرفر إلى مستوى تعزيز Boost Level 2 أو أعلى."
        if 'colour' in err_text or 'color' in err_text:
            return False, "تعذر تعيين الألوان المتحركة. تتطلب هذه الميزة (Enhanced Role Styles) حصول السيرفر على 3 تعزيزات على الأقل."
        return False, f"حدث خطأ أثناء التعديل: {e}"


async def do_remove_role_icon(bot, guild: discord.Guild, owner: discord.Member, role_id: int):
    role = guild.get_role(role_id)
    if not role:
        return False, "لم يتم العثور على الرتبة. من المحتمل أنها حُذفت من السيرفر."
    if role not in owner.roles:
        return False, "لا تمتلك هذه الرتبة حالياً في حسابك."
    if guild.me.top_role <= role:
        return False, "لا يمكن تعديل هذه الرتبة. يجب أن تكون رتبة البوت أعلى منها في إعدادات السيرفر."

    try:
        await role.edit(display_icon=None, reason=f"إزالة أيقونة الرتبة بواسطة {owner} (ID: {owner.id})")
        await log_action(bot, guild, owner, "remove_icon", target_id=owner.id, role_id=role_id)
        return True, f"تمت إزالة أيقونة رتبتك {role.mention} بنجاح."
    except discord.Forbidden:
        return False, "لا تتوفر لدي صلاحية كافية لتعديل هذه الرتبة."
    except discord.HTTPException as e:
        return False, f"حدث خطأ أثناء إزالة الأيقونة: {e}"
