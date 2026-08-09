"""
فحص الصور (بايتس مباشرة، بدون الحاجة لرابط عام) عن وجود محتوى عري/جنسي
باستخدام خدمة Sightengine (فيها باقة مجانية - sightengine.com).

الاستخدام:
    from utils.nsfw_check import is_image_nsfw
    flagged, score = await is_image_nsfw(image_bytes)
"""

import logging
import aiohttp

import config

log = logging.getLogger("nsfw_check")

SIGHTENGINE_URL = "https://api.sightengine.com/1.0/check.json"


async def is_image_nsfw(image_bytes: bytes) -> tuple[bool, float]:
    """
    يرجع (is_nsfw, score) بفحص بايتس الصورة مباشرة عبر Sightengine.
    لو صار خطأ بالاتصال أو ما في مفاتيح API معرّفة، بيرجع (False, 0.0)
    (فيل-سيف: ما منمنع الرفع بحال تعطلت الخدمة، بس بينسجل تحذير بالسجل).
    """
    if not config.SIGHTENGINE_API_USER or not config.SIGHTENGINE_API_SECRET:
        log.warning("SIGHTENGINE_API_USER/SECRET غير معرّفة في متغيرات البيئة - تم تخطي فحص NSFW")
        return False, 0.0

    data = aiohttp.FormData()
    data.add_field("media", image_bytes, filename="icon.png", content_type="application/octet-stream")
    data.add_field("models", "nudity-2.1")
    data.add_field("api_user", config.SIGHTENGINE_API_USER)
    data.add_field("api_secret", config.SIGHTENGINE_API_SECRET)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SIGHTENGINE_URL, data=data, timeout=15) as resp:
                result = await resp.json()
    except Exception as e:
        log.warning(f"تعذر الاتصال بخدمة فحص الصور: {e}")
        return False, 0.0

    nudity = result.get("nudity", {})
    score = max(
        nudity.get("sexual_activity", 0),
        nudity.get("sexual_display", 0),
        nudity.get("erotica", 0),
        nudity.get("raw", 0),
    )
    return score >= config.NSFW_THRESHOLD, score
