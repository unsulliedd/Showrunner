"""Reading text files whose encoding is not declared."""

from __future__ import annotations

from charset_normalizer import from_bytes

from showrunner.core.language import Language

# The usual pre-UTF-8 code page per language (ISO 639-3). A statistical guess misreads short files,
# so a known language decides.
_LEGACY_CODE_PAGES = {
    "tur": "cp1254",
    "ell": "cp1253",
    "ara": "cp1256",
    "heb": "cp1255",
    **dict.fromkeys(("rus", "ukr", "bul", "srp", "mkd", "bel"), "cp1251"),
    **dict.fromkeys(("pol", "ces", "slk", "hun", "ron", "hrv", "slv", "bos"), "cp1250"),
}


def decode_text(raw: bytes, language: Language | None = None) -> str:
    """UTF-8 first, then the language's legacy code page, then the best statistical guess."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    code_page = _LEGACY_CODE_PAGES.get(language.alpha3) if language else None
    if code_page:
        return raw.decode(code_page, errors="replace")
    best = from_bytes(raw).best()
    return str(best) if best else raw.decode("latin-1")
