"""Normalising register cells written in Gurmukhi, English, or a mix (pilot Part 5).

Registers at Punjab hiring centres mix scripts freely: Gurmukhi digits
(੦੧੨੩੪੫੬੭੮੯) next to ASCII ones, Punjabi words for units and machines, and
labels like "ਫ਼ੋਨ:" or "Mob." in front of numbers. These helpers turn such
cells into the plain values the validator checks. They never guess: anything
they cannot read stays as written, so validation flags it for a person.
"""

import re
from fractions import Fraction

GURMUKHI_DIGITS = "੦੧੨੩੪੫੬੭੮੯"
DEVANAGARI_DIGITS = "०१२३४५६७८९"
_DIGITS = str.maketrans(GURMUKHI_DIGITS + DEVANAGARI_DIGITS, "0123456789" * 2)


def to_ascii_digits(text: str) -> str:
    """Replace Gurmukhi and Devanagari digits with 0-9. Everything else is unchanged."""
    return text.translate(_DIGITS)


# --- Phone numbers -----------------------------------------------------------

def normalize_phone(raw: str) -> str:
    """'ਫ਼ੋਨ: ੯੮੭੬੫ ੪੩੨੧੦', '+91 98765-43210', '098765 43210' -> '9876543210'.

    Labels, spaces, dashes, dots, brackets and the danda (।) are dropped. A
    leading +91, 91 (12 digits) or 0 (11 digits) is removed. Two numbers in one
    cell stay too long and are flagged by validation.
    """
    s = to_ascii_digits(str(raw))
    has_plus = "+" in s
    digits = re.sub(r"\D", "", s)
    if has_plus and digits.startswith("91") and len(digits) == 12:
        return digits[2:]
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]
    return digits


# --- Acres ------------------------------------------------------------------

# Words that mean "acre" on a Punjab register. A killa is one acre.
ACRE_WORDS = (
    "ਏਕੜ", "ਏਕਡ਼", "ਕਿੱਲੇ", "ਕਿੱਲਾ", "ਕਿਲੇ", "ਕਿਲਾ", "ਕਿੱਲਿਆਂ",
    "acres", "acre", "ac.", "ac", "kille", "killa", "kila",
)
KANAL_WORDS = ("ਕਨਾਲ", "kanals", "kanal")
KANALS_PER_ACRE = 8  # Punjab: 1 acre = 8 kanal

_FRACTIONS = {"½": Fraction(1, 2), "¼": Fraction(1, 4), "¾": Fraction(3, 4)}


def _strip_words(s: str, words: tuple[str, ...]) -> tuple[str, bool]:
    found = False
    for w in sorted(words, key=len, reverse=True):
        pattern = re.escape(w) if not w.isascii() else r"(?<![a-z])" + re.escape(w) + r"(?![a-z])"
        s2 = re.sub(pattern, " ", s, flags=re.IGNORECASE)
        if s2 != s:
            found = True
            s = s2
    return s, found


def parse_acres(raw) -> tuple[str | None, str | None]:
    """Return (a plain decimal string, a warning or None).

    '੩.੫ ਏਕੜ' -> ('3.5', None); '4 kille' -> ('4', None); '3½' -> ('3.5', None);
    '2 1/2 acre' -> ('2.5', None); '4 ਕਨਾਲ' -> ('0.5', 'acres: converted from 4 kanal ...').
    Returns (None, None) when the cell does not hold one number; validation then flags it.
    """
    s = to_ascii_digits(str(raw)).strip().lower()
    s, _ = _strip_words(s, ACRE_WORDS)
    s, is_kanal = _strip_words(s, KANAL_WORDS)
    s = s.replace("।", " ").strip()

    total: Fraction | None = None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)?\s*([½¼¾])", s)
    m2 = re.fullmatch(r"(\d+)\s+(\d+)\s*/\s*(\d+)", s)
    m3 = re.fullmatch(r"(\d+)\s*/\s*(\d+)", s)
    if m:
        total = Fraction(m.group(1) or "0") + _FRACTIONS[m.group(2)]
    elif m2 and int(m2.group(3)) != 0:
        total = Fraction(int(m2.group(1))) + Fraction(int(m2.group(2)), int(m2.group(3)))
    elif m3 and int(m3.group(2)) != 0:
        total = Fraction(int(m3.group(1)), int(m3.group(2)))
    elif re.fullmatch(r"\d+(?:\.\d+)?", s):
        total = Fraction(s)
    if total is None:
        return None, None

    warning = None
    if is_kanal:
        kanal = total
        total = total / KANALS_PER_ACRE
        warning = f"acres: converted from {_fmt(kanal)} kanal ({KANALS_PER_ACRE} kanal = 1 acre), check the register"
    return _fmt(total), warning


def _fmt(x: Fraction) -> str:
    """Up to 4 decimals, no trailing zeros (validation then checks the 2-decimal rule)."""
    text = f"{float(x):.4f}".rstrip("0").rstrip(".")
    return text or "0"


# --- Service type -----------------------------------------------------------

_SERVICE_WORDS = {
    "ਸੁਪਰ": "super", "ਸੂਪਰ": "super", "ਹੈਪੀ": "happy", "ਸੀਡਰ": "seeder", "ਬੇਲਰ": "baler",
    "ਮਲਚਰ": "mulcher", "ਸੁਪਰਸੀਡਰ": "super seeder", "ਹੈਪੀਸੀਡਰ": "happy seeder",
}
_SERVICE_PHRASES = {
    "super seeder": "super_seeder", "superseeder": "super_seeder", "super": "super_seeder",
    "ss": "super_seeder", "s seeder": "super_seeder", "s s": "super_seeder",
    "happy seeder": "happy_seeder", "happyseeder": "happy_seeder", "happy": "happy_seeder",
    "hs": "happy_seeder", "h seeder": "happy_seeder", "h s": "happy_seeder",
    "baler": "baler", "bailer": "baler", "mulcher": "mulcher", "mulchar": "mulcher",
}


def normalize_service(raw) -> str | None:
    """'ਸੁਪਰ seeder', 'Super ਸੀਡਰ', 'ਬੇਲਰ (baler)', 'S.S.', 'happy-seeder' -> a service type, else None."""
    s = str(raw).strip().lower()
    for pa, en in sorted(_SERVICE_WORDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        s = s.replace(pa, f" {en} ")
    s = re.sub(r"[()\[\].,_\-/]+", " ", s)
    words: list[str] = []
    for w in s.split():
        if len(w) > 2 and w in words:  # 'baler baler' from 'ਬੇਲਰ (baler)'; keep 's s' from 'S.S.'
            continue
        words.append(w)
    phrase = " ".join(words)
    if phrase in ("super_seeder", "happy_seeder"):
        return phrase
    return _SERVICE_PHRASES.get(phrase)


# --- Dates with month names ---------------------------------------------------

_MONTHS = {
    # Punjabi (as in the contract) and common spellings
    "ਜਨਵਰੀ": 1, "ਫ਼ਰਵਰੀ": 2, "ਫਰਵਰੀ": 2, "ਮਾਰਚ": 3, "ਅਪ੍ਰੈਲ": 4, "ਅਪਰੈਲ": 4, "ਮਈ": 5, "ਜੂਨ": 6,
    "ਜੁਲਾਈ": 7, "ਅਗਸਤ": 8, "ਸਤੰਬਰ": 9, "ਸਿਤੰਬਰ": 9, "ਅਕਤੂਬਰ": 10, "ਨਵੰਬਰ": 11, "ਦਸੰਬਰ": 12,
    # English
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def month_name_date(raw: str) -> tuple[int, int, int | None] | None:
    """'18 ਅਕਤੂਬਰ', '੧੮ ਅਕਤੂਬਰ ੨੦੨੬', '18 Oct', 'Oct 18', '18-Oct-2026' -> (day, month, year or None)."""
    s = to_ascii_digits(str(raw)).strip().lower()
    s = re.sub(r"[,\-/.]+", " ", s)
    parts = s.split()
    if len(parts) not in (2, 3):
        return None
    month = None
    nums: list[int] = []
    for p in parts:
        if p in _MONTHS and month is None:
            month = _MONTHS[p]
        elif p.isdigit():
            nums.append(int(p))
        else:
            return None
    if month is None or not nums:
        return None
    day = nums[0]
    year = nums[1] if len(nums) > 1 else None
    if year is not None and year < 100:
        year += 2000
    return day, month, year
