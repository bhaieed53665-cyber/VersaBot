"""
فحص النصوص (متل اسم الرتبة) والتأكد من عدم احتوائها على ألفاظ بذيئة
بالعربي أو الإنجليزي، مع دعم لكشف محاولات التحايل (تكرار حروف، رموز بدل حروف).

الاستخدام:
    from utils.content_filter import contains_profanity
    ok, matched = contains_profanity("اسم الرتبة")
    if not ok:
        # ارفض العملية
"""

import re
import unicodedata

try:
    from better_profanity import profanity as _en_profanity
    _en_profanity.load_censor_words()
    _HAS_BETTER_PROFANITY = True
except ImportError:
    _HAS_BETTER_PROFANITY = False

# قائمة جذور عربية بذيئة/مسيئة شائعة. وسّعها حسب الحاجة (بدون تشكيل).
ARABIC_BAD_ROOTS = {
    # ألفاظ جنسية/بذيئة
    "كس", "طيز", "زب", "شرموط", "شرموطة", "قحبة", "عاهرة",
    "منيك", "منيوك", "خرا", "خره", "كسمك", "كسختك",
    "زانية", "لوطي", "خول", "متناك",
    "نيك", "نياك", "ينيك", "ينيكك", "معرص", "قواد", "قحبه",
    "شرموطه", "منيوكه", "واطي", "وسخ", "زبي",

    # شتائم عائلية/شخصية
    "ابن كلب", "ابن الكلب", "بنت كلب", "كلب", "حمار", "حيوان",
    "ابن حرام", "بنت حرام", "حقير", "نذل", "وقح", "زفت", "غبي",
    "احا", "تفو", "يلعن", "لعنة عليك",

    # سب الدين والإلحاد كشتيمة
    "كافر", "كفر", "ملحد", "الحاد", "لعنة الله", "الله يلعنك",
    "يلعن دينك", "دين امك", "سب الدين", "شتم الدين", "يخرب دينك",
    "لعنة على دينك", "دين ابوك",
}

_LEET_MAP = str.maketrans({
    "0": "و", "1": "ا", "3": "ع", "4": "ا", "@": "ا",
    "$": "س", "*": "", "-": "", "_": "", ".": "", " ": "",
})

_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
_ZERO_WIDTH = re.compile(r"[\u200B-\u200F\uFEFF]")


def _normalize_arabic(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"(.)\1{1,}", r"\1", text)
    return text


def _normalize_arabic_compact(text: str) -> str:
    """
    نفس التطبيع العربي، بس مع إزالة كل المسافات والفواصل بين الحروف،
    عشان نمسك محاولات التحايل متل: 'ك س م ك' أو 'ك.س.م.ك' أو 'ك-س-م-ك'
    """
    text = _normalize_arabic(text)
    text = re.sub(r"[\s\-_.,،*]+", "", text)
    return text


def _normalize_generic(text: str) -> str:
    text = text.lower().translate(_LEET_MAP)
    text = re.sub(r"(.)\1{1,}", r"\1", text)
    return text


def contains_profanity(text: str) -> tuple[bool, str | None]:
    """
    يرجع (is_clean, matched_word_or_None).
    is_clean=True يعني النص نظيف ومقبول.
    """
    if not text or not text.strip():
        return True, None

    normalized_ar = _normalize_arabic(text)
    normalized_ar_compact = _normalize_arabic_compact(text)
    normalized_generic = _normalize_generic(text)

    for root in ARABIC_BAD_ROOTS:
        root_norm = _normalize_arabic(root)
        root_compact = _normalize_arabic_compact(root)
        if root_norm in normalized_ar or root_compact in normalized_ar_compact:
            return False, root

    if _HAS_BETTER_PROFANITY:
        if _en_profanity.contains_profanity(text) or _en_profanity.contains_profanity(normalized_generic):
            return False, "english-profanity"

    return True, None
