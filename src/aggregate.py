"""Turn the raw resource into the monthly series declared by a profile.

Privacy: only the columns the profile needs are read (date, key, exclusion
flag, filter columns, summed columns), and only monthly aggregates leave this
module. Personal data in the raw file (for IBAMA: offender names, CPF/CNPJ)
is never loaded, let alone written to the repository.
"""

import fnmatch
import logging
import zipfile
from pathlib import Path

import pandas as pd

from src import monetary
from src.profile import Profile

logger = logging.getLogger(__name__)

CONTEXT_COLUMNS = ("excluded", "missing_key")


def parse_number(values: pd.Series, number_format: str = "plain") -> pd.Series:
    """Parse numbers; 'br' handles Brazilian decimals ('1.234,56', '1500,00')."""
    s = values.astype("string").str.strip()
    if number_format == "br":
        has_comma = s.str.contains(",", regex=False, na=False)
        s = s.where(~has_comma, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def parse_dates(values: pd.Series, formats: list[str] | None = None) -> pd.Series:
    """Parse dates; with `formats`, each value takes the first format that reads it.

    Without formats, the format is inferred value by value. Explicit formats are needed when
    a dataset mixes formats across files and one of them is day-first ('02/01/2024'), which
    inference would read as 1 February."""
    if not formats:
        return pd.to_datetime(values, errors="coerce", format="mixed")
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for fmt in formats:
        todo = out.isna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(values[todo], errors="coerce", format=fmt)
    return out


def needed_columns(profile: Profile) -> list[str]:
    cols = [profile["columns"]["date"]]
    if profile["columns"].get("key"):
        cols.append(profile["columns"]["key"])
    if profile.get("exclude"):
        cols.append(profile["exclude"]["column"])
    cols += [f["column"] for f in profile.get("filters", [])]
    cols += [s["column"] for s in profile.series.values() if s["kind"] == "sum"]
    return list(dict.fromkeys(cols))


def load_records(path: Path, profile: Profile) -> pd.DataFrame:
    """Read the needed columns from the downloaded resource (zip of CSVs or a CSV)."""
    spec = profile["file"]
    usecols = needed_columns(profile)
    # encoding_errors "replace": a file with a few bytes in another encoding is still read (only
    # the needed columns are kept, and a damaged date shows up in rows_invalid_date).
    read = dict(sep=spec.get("sep", ","), encoding=spec.get("encoding", "utf-8"), usecols=usecols, dtype=str,
                encoding_errors=spec.get("encoding_errors", "strict"))
    frames = []
    if spec.get("compression", "none") == "zip":
        pattern = spec.get("member_pattern", "*.csv")
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if fnmatch.fnmatch(name.lower(), pattern.lower()):
                    with zf.open(name) as fh:
                        frames.append(pd.read_csv(fh, **read))
    else:
        frames.append(pd.read_csv(path, **read))
    if not frames:
        raise ValueError(f"No file matching the profile was found in {path}")
    return pd.concat(frames, ignore_index=True)


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    for f in filters:
        col = df[f["column"]].astype("string").str.strip()
        if "in" in f:
            df = df[col.isin(f["in"])]
        elif "not_in" in f:
            df = df[~col.isin(f["not_in"])]
        else:
            df = df[col == str(f["equals"])]
    return df


def monthly_series(records: pd.DataFrame, profile: Profile, as_of: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """Aggregate records per month.

    Returns one column per profile series plus the context columns
    `excluded` (rows removed by the profile's exclusion rule) and
    `missing_key` (rows without an identifier), for every month up to the
    last complete month, and a dict of data-handling statistics.
    """
    cols = profile["columns"]
    stats = {"rows_read": int(len(records))}
    df = apply_filters(records, profile.get("filters", []))
    stats["rows_after_filters"] = int(len(df))

    df = df.assign(date=parse_dates(df[cols["date"]], cols.get("date_formats")))
    stats["rows_invalid_date"] = int(df["date"].isna().sum())
    df = df.dropna(subset=["date"])

    key = cols.get("key")
    if key:
        stats["rows_missing_key"] = int(df[key].isna().sum())
        # Rows sharing a non-empty key are true duplicates; keep one of each.
        dup = df[key].notna() & df.duplicated(subset=[key], keep="last")
        stats["rows_duplicate_key_dropped"] = int(dup.sum())
        df = df[~dup]
        df = df.assign(missing_key=df[key].isna())
    else:
        df = df.assign(missing_key=False)

    rule = profile.get("exclude")
    if rule:
        excluded = df[rule["column"]].astype("string").str.strip().str.upper().eq(str(rule["equals"]).upper())
    else:
        excluded = pd.Series(False, index=df.index)
    df = df.assign(excluded=excluded)
    stats["rows_excluded"] = int(excluded.sum())

    current = as_of.to_period("M")
    df = df.assign(month=df["date"].dt.to_period("M"))
    future = df["month"] > current
    stats["rows_future_date"] = int(future.sum())
    df = df[~future]
    if df.empty:
        raise ValueError("No records left after filters; check the profile")
    stats["last_record_month"] = str(df["month"].max())

    kept = df[~df["excluded"]]
    out = {}
    for name, s in profile.series.items():
        if s["kind"] == "count":
            out[name] = kept.groupby("month").size()
        else:
            values = parse_number(kept[s["column"]], s.get("number_format", "plain"))
            stats[f"rows_without_{name}"] = int(values.isna().sum())
            if s.get("convert_currency"):
                # Each value is converted at its own date, so a reform in the
                # middle of a month is handled exactly.
                values = values / monetary.conversion_factors(kept["date"], profile.monetary())
            out[name] = values.groupby(kept["month"]).sum(min_count=1)
    out["excluded"] = df.groupby("month")["excluded"].sum()
    out["missing_key"] = df.groupby("month")["missing_key"].sum()
    monthly = pd.DataFrame(out)
    # The current month is still being filled in; it is never analysed. With period.end
    # "last_record" (a portal that publishes, say, one file per year), the months after the last
    # record are not published yet, not empty: the series stops at the last month with records.
    stop = current
    if (profile.get("period") or {}).get("end") == "last_record":
        stop = min(stop, df["month"].max() + 1)
    full_index = pd.period_range(monthly.index.min(), stop, freq="M")
    monthly = monthly.reindex(full_index).fillna(0)
    monthly.index.name = "month"
    monthly = monthly[monthly.index < stop]
    for name, s in profile.series.items():
        if s["kind"] == "count":
            monthly[name] = monthly[name].astype(int)
    monthly = monthly.astype({c: int for c in CONTEXT_COLUMNS})
    stats["first_month"] = str(monthly.index.min())
    stats["last_complete_month"] = str(monthly.index.max())
    return monthly, stats


def analysis_window(monthly: pd.DataFrame, profile: Profile) -> pd.DataFrame:
    """Apply the profile's period and drop the sparse beginning of the series.

    The analysis starts at the first month from which the next 12 months of
    the first series have a median of at least `sparse_min_records`. Only
    the beginning is trimmed: quiet months later in the series (common in
    low-volume datasets) are data, not noise, and stay in the analysis.
    """
    period = profile.get("period") or {}
    if period.get("start"):
        monthly = monthly[monthly.index >= pd.Period(period["start"], freq="M")]
    if period.get("end") and period["end"] != "last_record":
        monthly = monthly[monthly.index <= pd.Period(period["end"], freq="M")]
    first = next(iter(profile.series))
    ahead = monthly[first][::-1].rolling(12, min_periods=12).median()[::-1]
    dense = ahead.index[ahead >= profile.get("sparse_min_records", 3)]
    if len(dense):
        monthly = monthly[monthly.index >= dense.min()]
    if len(monthly) < 36:
        raise ValueError(f"Only {len(monthly)} usable months; the detectors need at least 36")
    return monthly


def save_series(monthly: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = monthly.copy()
    out.index = out.index.astype(str)
    # Significant digits, not decimals: converted historical values can be
    # fractions of a cent and must not round to zero.
    out.to_csv(path, float_format="%.10g")


def load_series(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"month": str})
    df.index = pd.PeriodIndex(df.pop("month"), freq="M")
    df.index.name = "month"
    return df
