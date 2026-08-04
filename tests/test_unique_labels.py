"""unique_labels: the right-split parsing rule and the two silent-corruption
warnings (semicolon-separated export, decimal-comma values)."""
from collections import Counter

from src.extract.unique_labels import collect, warn_suspicious


def _csv(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_label_is_everything_before_the_last_two_commas(tmp_path):
    path = _csv(tmp_path, "ok.csv", [
        "360.001-RT401,2025-01-01 00:10,21.4",
        "360.001-RT401,2025-01-01 00:20,21.5",
        "navn, med komma,2025-01-01 00:10,1",  # commas in the label are fine
        "",  # blank lines skipped
    ])
    counter = collect([path])
    assert counter == Counter({"360.001-RT401": 2, "navn, med komma": 1})
    assert warn_suspicious(counter) == []


def test_semicolon_export_is_flagged(tmp_path):
    path = _csv(tmp_path, "semi.csv", [
        "RT401;2025-01-01 00:10;21.4",
        "RT501;2025-01-01 00:10;21.9",
    ])
    warnings = warn_suspicious(collect([path]))
    assert len(warnings) == 1 and "semicolon" in warnings[0]


def test_decimal_comma_shift_is_flagged(tmp_path):
    path = _csv(tmp_path, "komma.csv", [
        "RT401,2025-01-01 00:10,21,4",   # decimal comma -> label glued with date
        "RT501,01.01.2025 00:10,21,9",   # Norwegian date format also detected
    ])
    warnings = warn_suspicious(collect([path]))
    assert len(warnings) == 1 and "decimal comma" in warnings[0]
