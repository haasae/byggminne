from src.extract.control_number_map import (
    control_numbers_in_name,
    render_markdown,
    scan,
)


def test_control_number_extraction():
    assert control_numbers_in_name("20053401-Tasen-OU001 AV punkter 2025.csv") == ["20053401"]
    assert control_numbers_in_name("20056701-Skoyen BV punkter 2025.csv") == ["20056701"]
    # No standalone 8-digit run -> nothing (OS001 style, or 2025 is only 4 digits).
    assert control_numbers_in_name("Tasen Skole OS001 AV punkter 2025.csv") == []
    # A longer digit run must not be sliced into a spurious 8-digit match.
    assert control_numbers_in_name("123456789.csv") == []


def _make(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("label,ts,val\n", encoding="utf-8")


def test_scan_maps_control_number_to_parent_folder(tmp_path):
    _make(tmp_path, "tasen/20053401-Tasen-OU001 AV punkter 2025.csv")
    _make(tmp_path, "tasen/20053401-Tasen-OU002 AV punkter 2025.csv")
    _make(tmp_path, "skoyen/20056701-Skoyen AV punkter 2025.csv")
    _make(tmp_path, "tasen/Tasen Skole OS001 AV punkter 2025.csv")  # no control number

    mapping, conflicts, n_files, n_without = scan(tmp_path)
    assert mapping["20053401"]["area"] == "tasen"
    assert len(mapping["20053401"]["files"]) == 2          # both OU files accumulate
    assert mapping["20056701"]["area"] == "skoyen"
    assert conflicts == {}
    assert n_files == 4 and n_without == 1


def test_scan_flags_area_conflict(tmp_path):
    _make(tmp_path, "tasen/20053401-Tasen-OU001.csv")
    _make(tmp_path, "skoyen/20053401-elsewhere.csv")   # same number, different area
    mapping, conflicts, _, _ = scan(tmp_path)
    assert "20053401" in conflicts
    assert set(conflicts["20053401"]) == {"tasen", "skoyen"}


def test_render_is_deterministic_and_cites_files(tmp_path):
    _make(tmp_path, "tasen/20053401-Tasen-OU001.csv")
    mapping, conflicts, n_files, n_without = scan(tmp_path)
    md = render_markdown(mapping, conflicts, n_files, n_without)
    assert "| 20053401 | tasen |" in md
    assert "20053401-Tasen-OU001.csv" in md
    assert render_markdown(mapping, conflicts, n_files, n_without) == md
