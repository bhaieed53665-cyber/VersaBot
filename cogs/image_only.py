"""
كل إعدادات البوت تُقرأ من متغيرات البيئة هون بمكان واحد.
لا يوجد أي معرف (ID) مكتوب مباشرة داخل باقي ملفات الكود.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_int_env(name: str, default: int = 0) -> int:
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_id_list_env(name: str) -> list[int]:
    raw = os.getenv(name, "")
    return [int(cid.strip()) for cid in raw.split(",") if cid.strip()]


TOKEN = os.getenv("DISCORD_TOKEN")

# قنوات ومعرفات أساسية (كانت هاردكود بالكود القديم، الآن كلها من الـ env)
TICKET_CHANNEL_ID = _get_int_env("TICKET_CHANNEL_ID")
ADMIN_USER_ID = _get_int_env("ADMIN_USER_ID")
LOG_CHANNEL_ID = _get_int_env("LOG_CHANNEL_ID")
VIP_CHANNEL_ID = _get_int_env("VIP_CHANNEL_ID")

# قناة سجل التدقيق (اختيارية) - لو تُركت فارغة، سجل التدقيق بيتخزن بقاعدة البيانات فقط
# بدون إرسال Embed مباشر لأي قناة
AUDIT_CHANNEL_ID = _get_int_env("AUDIT_CHANNEL_ID")

AUTO_REACT_CHANNEL_IDS = _get_id_list_env("AUTO_REACT_CHANNEL_IDS")
AUTO_REACT_EMOJI = os.getenv("AUTO_REACT_EMOJI", "📷")

# قنوات "صور فقط": أي رسالة بهاي القنوات ما فيها صورة مرفقة بينحذف تلقائياً بصمت (بدون رسالة تنبيه)
IMAGE_ONLY_CHANNEL_IDS = _get_id_list_env("IMAGE_ONLY_CHANNEL_IDS")

MAX_SHARED_MEMBERS = _get_int_env("MAX_SHARED_MEMBERS", 2)

DB_PATH = os.getenv("DB_PATH", "subscriptions.db")
