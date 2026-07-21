from src.score.normalize import code_prefix, normalize_text


def test_normalize_trims_and_casefolds():
    assert normalize_text("  Tilluft  ") == "tilluft"
    assert normalize_text("Varmt   Tappevann") == "varmt tappevann"


def test_normalize_preserves_norwegian_diacritics():
    # ae/oe/aa must survive (only NFC + casefold), so Kjoling != Kjoeling.
    assert normalize_text("Kjøling") == "kjøling"
    assert normalize_text("Kjøling") != normalize_text("Kjoling")


def test_normalize_none_stays_none():
    assert normalize_text(None) is None


def test_code_prefix():
    assert code_prefix("3200") == "320"
    assert code_prefix("320") == "320"
    assert code_prefix("434.003") == "434"
    assert code_prefix("36") == "36"          # fewer than 3 digits -> what's there
    assert code_prefix("RTA") is None          # no leading digits
    assert code_prefix(None) is None
