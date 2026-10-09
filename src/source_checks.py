"""Source checks: problems of the published files that distort a monthly series if unnoticed.

Found when a second and a third portal were added (Recife's traffic notices: three date formats
across the yearly files, one of them day-first; one file that is not valid UTF-8; datasets that
stop years before today). Every run records them in the source manifest and the dashboard lists
them, so whoever clones the toolkit for another portal sees them on the first run instead of
discovering them in the anomalies. Each check says whether the profile already handles the
problem ("info") or whether it may be changing the results ("warning"), and what to set.

Only shapes of the date values (digits replaced by 9) and counts are kept, never values.
"""

import codecs
import fnmatch
import re
import zipfile
from pathlib import Path

import pandas as pd

# A shape must cover at least this share of the dated rows to count as a format in use
# (a handful of malformed values is the invalid_dates check, not a second format).
MIN_SHAPE_SHARE = 0.001
INVALID_DATE_SHARE = 0.005
LAG_MONTHS = 3          # months without any record before today that suggest a publication lag
DAY_MONTH = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-]\d{4}")

_counter = [0]


def _count_errors(exc: UnicodeDecodeError):
    _counter[0] += exc.end - exc.start
    return "�", exc.end


codecs.register_error("layer3-count", _count_errors)


def invalid_bytes(path: Path, spec: dict) -> int:
    """Bytes of the resource that are not valid in the profile's encoding (streamed, nothing kept)."""
    encoding = spec.get("encoding", "utf-8")

    def count(fh) -> int:
        _counter[0] = 0
        decoder = codecs.getincrementaldecoder(encoding)(errors="layer3-count")
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
        return _counter[0]

    if spec.get("compression", "none") == "zip":
        pattern = spec.get("member_pattern", "*.csv").lower()
        with zipfile.ZipFile(path) as zf:
            total = 0
            for name in zf.namelist():
                if fnmatch.fnmatch(name.lower(), pattern):
                    with zf.open(name) as fh:
                        total += count(fh)
            return total
    with open(path, "rb") as fh:
        return count(fh)


def date_profile(values: pd.Series) -> dict:
    """Shapes of the date values ('2025-01-02' -> '9999-99-99') and day/month evidence."""
    s = values.dropna().astype(str).str.strip()
    s = s[s != ""]
    shapes = s.str.replace(r"\d", "9", regex=True).value_counts()
    keep = shapes[shapes >= max(1, MIN_SHAPE_SHARE * len(s))]
    out = {"dated_rows": int(len(s)), "shapes": {k: int(v) for k, v in keep.head(5).items()}}
    dm = s.str.extract(DAY_MONTH).dropna().astype(int)
    if len(dm):
        out["first_field_over_12"] = int((dm[0] > 12).sum())    # proves day-first
        out["second_field_over_12"] = int((dm[1] > 12).sum())   # proves month-first
    return out


def evaluate(profile, files: list[dict], stats: dict, as_of: pd.Timestamp) -> list[dict]:
    """The checks of one run. `files`: per resource, {"resource_name", "invalid_bytes", "dates"}."""
    checks = []
    formats = profile["columns"].get("date_formats")
    shapes = sorted({sh for f in files for sh in f["dates"]["shapes"]})
    # Only the date part matters: '2024-01-02' and '2024-01-02 10:00:00' are read alike.
    if len({re.split(r"[ T]", sh)[0] for sh in shapes}) > 1:
        checks.append({
            "check": "mixed_date_formats", "level": "info" if formats else "warning",
            "params": {"shapes": shapes,
                       "files": {f["resource_name"]: sorted(f["dates"]["shapes"]) for f in files}},
        })
    ambiguous = [f["resource_name"] for f in files
                 if any(DAY_MONTH.match(sh.replace("9", "1")) for sh in f["dates"]["shapes"])]
    if ambiguous and not formats:
        day_first = sum(f["dates"].get("first_field_over_12", 0) for f in files)
        month_first = sum(f["dates"].get("second_field_over_12", 0) for f in files)
        checks.append({"check": "ambiguous_day_month", "level": "warning",
                       "params": {"files": ambiguous, "day_first_evidence": day_first,
                                  "month_first_evidence": month_first}})
    bad = {f["resource_name"]: f["invalid_bytes"] for f in files if f["invalid_bytes"]}
    if bad:
        handled = profile["file"].get("encoding_errors", "strict") != "strict"
        checks.append({"check": "invalid_encoding", "level": "info" if handled else "warning",
                       "params": {"encoding": profile["file"].get("encoding", "utf-8"), "files": bad}})
    rows = stats.get("rows_after_filters") or 0
    if rows and stats.get("rows_invalid_date", 0) / rows >= INVALID_DATE_SHARE:
        checks.append({"check": "invalid_dates", "level": "warning",
                       "params": {"rows": stats["rows_invalid_date"], "share": round(stats["rows_invalid_date"] / rows, 4)}})
    last = stats.get("last_record_month")
    if last:
        lag = (as_of.to_period("M") - pd.Period(last, freq="M")).n - 1
        if lag >= LAG_MONTHS:
            handled = (profile.get("period") or {}).get("end") == "last_record"
            checks.append({"check": "publication_lag", "level": "info" if handled else "warning",
                           "params": {"last_record_month": last, "months_without_records": lag}})
    if stats.get("rows_future_date"):
        checks.append({"check": "future_dates", "level": "info", "params": {"rows": stats["rows_future_date"]}})
    return checks


MESSAGES = {
    "mixed_date_formats": "dates come in {n} shapes across the files, with more than one order of day, month and year; {fix}",
    "ambiguous_day_month": "day/month order is ambiguous in {files} (day-first evidence {day_first_evidence}, "
                           "month-first {month_first_evidence}); declare columns.date_formats",
    "invalid_encoding": "{n} file(s) have bytes that are not valid {encoding}; {fix}",
    "invalid_dates": "{rows} rows ({share:.1%}) have a date that could not be read",
    "publication_lag": "no record after {last_record_month} ({months_without_records} months); {fix}",
    "future_dates": "{rows} rows dated after today were left out",
}


def describe(check: dict) -> str:
    """One line for the log (the dashboard has its own texts, in both languages)."""
    p, info = dict(check["params"]), check["level"] == "info"
    p["n"] = len(p.get("shapes") or p.get("files") or [])
    p["fix"] = {"mixed_date_formats": "read with columns.date_formats" if info else "declare columns.date_formats",
                "invalid_encoding": "read with encoding_errors" if info else "check file.encoding or set file.encoding_errors",
                "publication_lag": "the series stops there (period.end last_record)" if info
                else "the months after it count as zero; set period.end to \"last_record\" if the portal publishes late",
                }.get(check["check"], "")
    return f"[{check['level']}] {check['check']}: " + MESSAGES[check["check"]].format(**p)
