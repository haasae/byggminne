from src.profile.series_stats import (
    DISTINCT_CAP,
    file_kind,
    profile_files,
)


def _write(path, lines, encoding="utf-8"):
    path.write_text("\n".join(lines) + "\n", encoding=encoding)


def _rows(stats, label):
    return stats[label].to_row(label)


def test_file_kind_detection():
    assert file_kind("20053401-Tasen-OU001 AV punkter 2025.csv") == "AV"
    assert file_kind("Tasen Skole OS001 BV punkter 2025.csv") == "BV"
    assert file_kind("results_with_weather.csv") is None


def test_basic_stats_binary_and_temperature(tmp_path):
    av = tmp_path / "X AV punkter 2025.csv"
    _write(av, [
        "TMP,2025-01-01 00:00:00.000,21.5",
        "BIN,2025-01-01 00:00:00.000,0",
        "TMP,2025-01-01 00:10:00.000,22.0",
        "BIN,2025-01-01 00:10:00.000,1",
        "TMP,2025-01-01 00:20:00.000,21.8",
        "BIN,2025-01-01 00:20:00.000,0",
    ], encoding="utf-8-sig")  # BOM: the reader must tolerate it

    stats, n_malformed = profile_files([av])
    assert n_malformed == 0

    bin_row = _rows(stats, "BIN")
    assert bin_row["n_rows"] == 3 and bin_row["n_num"] == 3
    assert bin_row["is_binary"] is True
    assert bin_row["distinct_count"] == 2 and bin_row["values"] == [0.0, 1.0]
    assert bin_row["file_kinds"] == ["AV"]
    assert bin_row["first_ts"] == "2025-01-01 00:00:00.000"
    assert bin_row["last_ts"] == "2025-01-01 00:20:00.000"

    tmp_row = _rows(stats, "TMP")
    assert tmp_row["is_binary"] is False
    assert tmp_row["min"] == 21.5 and tmp_row["max"] == 22.0
    assert abs(tmp_row["mean"] - (21.5 + 22.0 + 21.8) / 3) < 1e-9
    assert tmp_row["monotonic_nondecreasing"] is False  # 22.0 -> 21.8 decreases
    assert tmp_row["n_decreases"] == 1


def test_monotonic_counter_and_constant_point(tmp_path):
    f = tmp_path / "data.csv"
    _write(f, [
        "CTR,2025-01-01 00:00:00.000,10",
        "CTR,2025-01-01 01:00:00.000,10",
        "CTR,2025-01-01 02:00:00.000,15.5",
        "CONST,2025-01-01 00:00:00.000,7",
        "CONST,2025-01-01 01:00:00.000,7",
    ])
    stats, _ = profile_files([f])
    ctr = _rows(stats, "CTR")
    assert ctr["monotonic_nondecreasing"] is True and ctr["n_decreases"] == 0
    const = _rows(stats, "CONST")
    assert const["distinct_count"] == 1 and const["values"] == [7.0]
    # A single-row label has no pairs to judge -> monotonic is None.
    single = tmp_path / "single.csv"
    _write(single, ["ONE,2025-01-01 00:00:00.000,1"])
    stats2, _ = profile_files([single])
    assert _rows(stats2, "ONE")["monotonic_nondecreasing"] is None


def test_bad_values_malformed_and_out_of_order(tmp_path):
    f = tmp_path / "messy.csv"
    _write(f, [
        "L,2025-01-01 02:00:00.000,5",
        "L,2025-01-01 01:00:00.000,99",     # goes backwards in time
        "L,2025-01-01 03:00:00.000,abc",    # unparseable value
        "no-commas-at-all",                  # malformed line
        "L,2025-01-01 04:00:00.000,6",
    ])
    stats, n_malformed = profile_files([f])
    assert n_malformed == 1
    row = _rows(stats, "L")
    assert row["n_rows"] == 4               # malformed line never reached a label
    assert row["n_bad_values"] == 1
    assert row["n_out_of_order"] == 1
    # The stray backwards row must not have produced a decrease (5 -> 6 is clean).
    assert row["n_decreases"] == 0
    assert row["first_ts"] == "2025-01-01 01:00:00.000"  # min ts still tracked
    assert row["last_ts"] == "2025-01-01 04:00:00.000"


def test_distinct_cap(tmp_path):
    f = tmp_path / "analog.csv"
    _write(f, [f"A,2025-01-01 00:{i:02d}:00.000,{i}.25" for i in range(DISTINCT_CAP + 5)])
    stats, _ = profile_files([f])
    row = _rows(stats, "A")
    assert row["distinct_capped"] is True
    assert row["distinct_count"] is None
    assert row["values"] is None
    assert row["is_binary"] is False


def test_label_filter_and_commas_in_label(tmp_path):
    f = tmp_path / "mixed.csv"
    _write(f, [
        "KEEP,2025-01-01 00:00:00.000,1",
        "DROP,2025-01-01 00:00:00.000,2",
    ])
    stats, _ = profile_files([f], labels={"KEEP"})
    assert set(stats) == {"KEEP"}
