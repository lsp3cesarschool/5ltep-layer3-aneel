"""Currency reforms: conversion of nominal values and events for the judge.

The reforms live in a hand-editable JSON (profiles/monetary/*.json). A value
recorded on date d is divided by the product of the divisors of every reform
that took effect after d, which expresses it in the current currency. This
removes the artificial level shifts a reform creates (e.g. /1000 overnight);
it is not an inflation adjustment.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src import config


def load(rel_path: str) -> dict:
    return json.loads((config.ROOT / rel_path).read_text(encoding="utf-8"))


def conversion_factors(dates: pd.Series, reforms: dict) -> np.ndarray:
    """Divisor that brings a value recorded on each date to the current currency."""
    factor = np.ones(len(dates))
    d = pd.to_datetime(dates).to_numpy()
    for change in reforms["changes"]:
        took_effect = np.datetime64(pd.Timestamp(change["date"]))
        factor = np.where(d < took_effect, factor * float(change["divide_by"]), factor)
    return factor


def as_events(reforms: dict) -> list[dict]:
    events = []
    for c in reforms["changes"]:
        plan = f", {c['plan']}" if c.get("plan") else ""
        ratio = f"1 new unit = {c['divide_by']:,} old units" if c["divide_by"] != 1 else "at par"
        events.append({
            "month": c["date"][:7],
            "kind": "monetary",
            "label": f"Currency reform: {c['from']} replaced by {c['to']} ({ratio}){plan}",
            "source": c["source"],
            "status": "verified",
        })
    return events


def validate(reforms: dict, path: Path | str = "") -> None:
    for c in reforms.get("changes", []):
        missing = {"date", "from", "to", "divide_by", "source"} - c.keys()
        if missing:
            raise ValueError(f"{path}: currency change {c} is missing {sorted(missing)}")
        pd.Timestamp(c["date"])
        if float(c["divide_by"]) <= 0:
            raise ValueError(f"{path}: divide_by must be positive in {c}")
