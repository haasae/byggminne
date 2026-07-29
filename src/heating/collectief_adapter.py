"""COLLECTiEF dataset adapter -- the ONLY file that knows COLLECTiEF exists.

Everything downstream consumes generic zone-file records and row iterators.
Layout on disk (see knowledge_base/collectief_survey.md for the landmines):

    <root>/Buildings/B0X/"Thermal zone"/<zone>.csv   # folder name has a space
    <root>/Weather/weather.csv

Zone CSVs share one padded 1-min grid; rows are `ts,val,val,val` with empty
fields for missing samples. Dispatch is ALWAYS on the header line, never the
filename (the B01 orphan B01-MA-A-B-3.csv looks like a T zone but carries a
COOL header).
"""
import re
from pathlib import Path

# Header (minus Timestamp) -> kind. Anything else becomes "other".
_KINDS = {
    ("T_Actualvalue", "T_Setvalue", "T_Gain"): "t_triple",
    ("CO2_Actualvalue", "CO2_Setvalue", "CO2_Gain"): "co2_triple",
    ("COOL_Gain",): "cool_gain",
    ("VAV_Gain",): "vav_gain",
    ("COOL_Setvalue", "COOL_Gain"): "cool_set_gain",
    ("COOL_Actualvalue",): "cool_actual",
}

_THERMAL_DIR = re.compile(r"^thermal ?zones?$", re.IGNORECASE)


class ZoneFile:
    __slots__ = ("building", "zone", "path", "kind", "columns")

    def __init__(self, building, zone, path, kind, columns):
        self.building = building
        self.zone = zone
        self.path = path
        self.kind = kind
        self.columns = columns


def read_header(path):
    """First line -> list of column names (BOM-stripped)."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        return fh.readline().rstrip("\r\n").split(",")


def classify_header(columns):
    if not columns or columns[0] != "Timestamp":
        return "other"
    return _KINDS.get(tuple(columns[1:]), "other")


def _thermal_dir(building_dir):
    for child in building_dir.iterdir():
        if child.is_dir() and _THERMAL_DIR.match(child.name):
            return child
    return None


def discover(root, buildings=None):
    """Yield ZoneFile for every zone CSV, sorted by (building, zone).

    root: dataset root (contains Buildings/). buildings: optional iterable of
    building folder names to include (e.g. {"B07", "B02"}).
    """
    buildings_dir = Path(root) / "Buildings"
    if not buildings_dir.is_dir():
        raise FileNotFoundError(f"no Buildings/ under {root}")
    wanted = {b.upper() for b in buildings} if buildings else None
    for bdir in sorted(p for p in buildings_dir.iterdir() if p.is_dir()):
        if wanted and bdir.name.upper() not in wanted:
            continue
        tdir = _thermal_dir(bdir)
        if tdir is None:
            continue
        for csv_path in sorted(tdir.glob("*.csv")):
            columns = read_header(csv_path)
            yield ZoneFile(
                building=bdir.name,
                zone=csv_path.stem,
                path=csv_path,
                kind=classify_header(columns),
                columns=columns,
            )


def weather_path(root):
    return Path(root) / "Weather" / "weather.csv"


def _norm_date(txt):
    """'2022-08-31 ...' or '31/08/2022 ...' -> '2022-08-31' (survey: B02/B07
    meters use DD/MM/YYYY). Returns None for unparseable text."""
    if len(txt) >= 10:
        if txt[4] == "-":
            return txt[:10]
        if txt[2] == "/" and txt[5] == "/":
            return f"{txt[6:10]}-{txt[3:5]}-{txt[0:2]}"
    return None


def read_weather_daily(root):
    """weather.csv -> {date: mean air temp}. Skips -999 sentinels.

    Timestamps verified UTC (data_observations.md, Phase 0)."""
    sums, counts = {}, {}
    with open(weather_path(root), "r", encoding="utf-8-sig") as fh:
        header = fh.readline().rstrip("\r\n").split(",")
        col = header.index("Air temperature")
        for line in fh:
            parts = line.rstrip("\r\n").split(",")
            try:
                v = float(parts[col])
            except (ValueError, IndexError):
                continue
            if v <= -900:
                continue
            date = _norm_date(parts[0])
            if date:
                sums[date] = sums.get(date, 0.0) + v
                counts[date] = counts.get(date, 0) + 1
    return {d: sums[d] / counts[d] for d in sums}


def read_meter_daily(root, building, column="main"):
    """Meters/meters.csv -> {date: kWh sum of `column`} for one building.

    Handles the survey quirks: DD/MM/YYYY dates (B02/B07), unnamed time
    column (B02 header is ',main'), empty values before meter liveness.
    """
    path = Path(root) / "Buildings" / building / "Meters" / "meters.csv"
    days = {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        header = fh.readline().rstrip("\r\n").split(",")
        col = header.index(column)
        for line in fh:
            parts = line.rstrip("\r\n").split(",")
            try:
                v = float(parts[col])
            except (ValueError, IndexError):
                continue
            date = _norm_date(parts[0])
            if date:
                days[date] = days.get(date, 0.0) + v
    return days
