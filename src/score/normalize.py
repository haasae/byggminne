"""Text normalization for COMPARISON ONLY -- never mutate stored data.

Norwegian diacritics (ae/oe/aa) are preserved: we only NFC-normalize, casefold,
and collapse whitespace, so 'Tilluft ' and 'tilluft' compare equal while
'Kjoling' and 'Kjoeling' stay distinct. Folding diacritics is intentionally NOT
done by default (it would risk false matches); synonym/typo equivalence belongs
in the knowledge base, not in the judge.
"""
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value):
    """NFC + casefold + collapse internal whitespace + trim. None stays None."""
    if value is None:
        return None
    text = unicodedata.normalize("NFC", str(value))
    text = text.casefold()
    return _WHITESPACE.sub(" ", text).strip()


def code_prefix(value, n: int = 3):
    """Leading digit run of an NS code, truncated to n digits ('3200' -> '320').

    Returns None for None or for a code with no leading digits (e.g. a 3-letter
    component code), so the caller can fall back to exact comparison."""
    if value is None:
        return None
    digits = ""
    for ch in str(value).strip():
        if ch.isdigit():
            digits += ch
        else:
            break
    return digits[:n] if digits else None
