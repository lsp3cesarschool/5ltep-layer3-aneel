"""Profiles: declarative description of *what* Layer 3 analyses.

A profile is a JSON file in profiles/ naming the CKAN portal, dataset and
resource, how to read the file, which rows to keep (the data cut), which
monthly series to build, the domain text and category taxonomy given to the
LLM, and the event calendar. Adapting the toolkit to another dataset, cut or
portal means writing a new profile; no code changes. See the README.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from src import config, monetary

REQUIRED = ("id", "title", "source", "file", "columns", "series", "domain", "record_label", "categories")
SERIES_KINDS = ("count", "sum")


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    results_dir: Path
    series: Path
    manifest: Path
    detections: Path
    drift: Path
    judgments: Path
    reviews: Path
    summary: Path
    run_log: Path
    dashboard: Path
    translations: Path

    @classmethod
    def for_profile(cls, profile_id: str, root: Path | None = None) -> "Paths":
        root = root or config.ROOT
        data, results = root / "data" / profile_id, root / "results" / profile_id
        return cls(
            data_dir=data,
            results_dir=results,
            series=data / "monthly_series.csv",
            manifest=data / "source_manifest.json",
            detections=results / "detections.csv",
            drift=results / "drift_points.json",
            judgments=results / "judgments.json",
            reviews=results / "reviews.json",
            summary=results / "layer3_summary.json",
            run_log=results / "run_log.jsonl",
            dashboard=root / "docs" / "data" / f"{profile_id}.json",
            translations=results / "translations.json",
        )


class Profile:
    def __init__(self, raw: dict, path: Path | None = None):
        validate(raw)
        self.raw = raw
        self.path = path
        self.id = raw["id"]
        self.paths = Paths.for_profile(self.id)
        if raw.get("monetary_file"):
            monetary.validate(self.monetary(), raw["monetary_file"])

    def __getitem__(self, key):
        return self.raw[key]

    def get(self, key, default=None):
        return self.raw.get(key, default)

    @property
    def series(self) -> dict[str, dict]:
        return {s["name"]: s for s in self.raw["series"]}

    @property
    def categories(self) -> dict[str, str]:
        return self.raw["categories"]

    def monetary(self) -> dict | None:
        rel = self.raw.get("monetary_file")
        return monetary.load(rel) if rel else None

    def events(self, include_suggested: bool | None = None) -> list[dict]:
        """Events for the judge: the calendar plus the currency reforms.

        Entries marked "rejected" by the steward are always left out; entries
        still "suggested" (proposed by the LLM, not yet checked) are included
        only when the profile allows it, and are flagged as unverified.
        Suggestions the model made from memory ("origin": "llm-memory") are
        never included before a steward verifies them: a first run showed a
        4B model inventing laws and impeachments when not grounded on a source.
        """
        if include_suggested is None:
            # Off unless a profile turns it on: suggestions come from editable sources (Wikipedia)
            # and would reach the prompt unchecked (SECURITY.md). Only verified events by default.
            include_suggested = self.raw.get("events_include_suggested", False)
        events = []
        rel = self.raw.get("events_file")
        if rel:
            events += json.loads((config.ROOT / rel).read_text(encoding="utf-8"))["events"]
        reforms = self.monetary()
        if reforms:
            events += monetary.as_events(reforms)
        out = []
        for ev in events:
            status = ev.get("status", "verified")
            if status == "rejected":
                continue
            if status == "suggested" and (not include_suggested or ev.get("origin") == "llm-memory"):
                continue
            out.append({**ev, "status": status})
        return sorted(out, key=lambda e: e["month"])


def validate(raw: dict) -> None:
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ValueError(f"Profile is missing required keys: {missing}")
    if "date" not in raw["columns"]:
        raise ValueError("Profile 'columns' must name the 'date' column")
    names = set()
    for s in raw["series"]:
        if s.get("kind") not in SERIES_KINDS:
            raise ValueError(f"Series {s.get('name')!r}: kind must be one of {SERIES_KINDS}")
        if s["kind"] == "sum" and not s.get("column"):
            raise ValueError(f"Series {s['name']!r}: kind 'sum' needs a 'column'")
        if s.get("convert_currency") and not raw.get("monetary_file"):
            raise ValueError(f"Series {s['name']!r}: convert_currency needs a profile 'monetary_file'")
        if s["name"] in names:
            raise ValueError(f"Duplicate series name {s['name']!r}")
        names.add(s["name"])
    if len(raw["series"]) < 1:
        raise ValueError("Profile needs at least one series")
    for f in raw.get("filters", []):
        if "column" not in f or not ({"in", "not_in", "equals"} & f.keys()):
            raise ValueError(f"Filter {f} needs 'column' and one of 'in', 'not_in', 'equals'")
    if not raw["categories"] or "INVALID" in raw["categories"]:
        raise ValueError("Profile needs a non-empty category taxonomy (INVALID is reserved)")


def default_id() -> str:
    """PROFILE if set, else the first scheduled profile, else the first profile."""
    if config.DEFAULT_PROFILE:
        return config.DEFAULT_PROFILE
    raws = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.PROFILES_DIR.glob("*.json"))]
    if not raws:
        raise FileNotFoundError(f"No profile in {config.PROFILES_DIR}")
    scheduled = [r["id"] for r in raws if r.get("scheduled")]
    return (scheduled or [raws[0]["id"]])[0]


def load(name_or_path: str | None = None) -> Profile:
    """Load a profile by id (profiles/<id>.json) or by file path."""
    name = name_or_path or default_id()
    path = Path(name)
    if not path.suffix:
        path = config.PROFILES_DIR / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Profile(raw, path)


def available() -> list[Profile]:
    return [load(str(p)) for p in sorted(config.PROFILES_DIR.glob("*.json"))]
