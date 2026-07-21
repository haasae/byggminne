import pytest

from src.decode.context_pack import KB_FILES, OPTIONAL_KB_FILES, build_context_pack


def test_pack_contains_every_kb_source_and_schema():
    context, version = build_context_pack()
    for rel in KB_FILES:
        assert f"===== SOURCE: {rel} =====" in context
    for rel in OPTIONAL_KB_FILES:
        # Present or not, every optional source appears as a section: verbatim
        # content or an explicit NOT AVAILABLE stub -- never silently absent.
        assert f"===== SOURCE: {rel}" in context
    assert "OUTPUT SCHEMA" in context
    assert len(version) == 12


def test_kb_version_is_deterministic():
    _, v1 = build_context_pack()
    _, v2 = build_context_pack()
    assert v1 == v2


def test_missing_kb_file_is_fatal(tmp_path):
    """A renamed/deleted KB file must fail loudly, never silently shrink the
    pack (the silent-skip regression)."""
    # tmp_path has none of the KB files, so all of them are missing.
    with pytest.raises(FileNotFoundError) as exc:
        build_context_pack(root=tmp_path)
    for rel in KB_FILES:
        assert rel in str(exc.value)


def test_one_missing_file_is_named(tmp_path):
    # Recreate all KB files but one under a fake root; the error names only it.
    present, absent = KB_FILES[:-1], KB_FILES[-1]
    for rel in present:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("stub", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as exc:
        build_context_pack(root=tmp_path)
    assert absent in str(exc.value)
    for rel in present:
        assert rel not in str(exc.value)


def test_missing_optional_file_degrades_to_stub(tmp_path):
    """User-supplied standards (not in the public repo) must not be fatal:
    the pack gets an explicit NOT AVAILABLE section instead."""
    for rel in KB_FILES:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("stub", encoding="utf-8")
    context, version = build_context_pack(root=tmp_path)
    for rel in OPTIONAL_KB_FILES:
        assert f"===== SOURCE: {rel} (NOT AVAILABLE) =====" in context
    assert len(version) == 12
