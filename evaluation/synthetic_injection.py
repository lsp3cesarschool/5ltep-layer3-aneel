"""Synthetic injection benchmark for the stage-1 detectors.

Ground truth is known by construction: one anomaly at a time is injected into
the real monthly series of a profile, and we check whether each detector and
the ensemble flag it, and how many *new* flags the injection causes elsewhere
(induced false alarms). Months already flagged in the clean series, and their
neighbours, are never used as injection points.

Anomaly types (multiplicative, in the original scale):
  spike       one month x MAGNITUDE
  dip         one month / MAGNITUDE (e.g. a partial reporting failure)
  gap         two consecutive months set to 0 (e.g. records missing)
  level_shift every month from t on x MAGNITUDE (sustained; also scored for Page-Hinkley)

Usage:
  python evaluation/synthetic_injection.py --profile ibama-autos-infracao --trials 20
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import aggregate, config, detectors  # noqa: E402
from src import profile as profiles  # noqa: E402

TYPES = ("spike", "dip", "gap", "level_shift")


def inject(values: pd.Series, kind: str, t: int, magnitude: float) -> tuple[pd.Series, list[int]]:
    v = values.copy().astype(float)
    if kind == "spike":
        v.iloc[t] *= magnitude
        return v, [t]
    if kind == "dip":
        v.iloc[t] /= magnitude
        return v, [t]
    if kind == "gap":
        v.iloc[t : t + 2] = 0.0
        return v, [t, t + 1]
    if kind == "level_shift":
        v.iloc[t:] *= magnitude
        return v, [t, t + 1, t + 2]  # detection counts if flagged within 3 months of onset
    raise ValueError(kind)


def f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=config.DEFAULT_PROFILE)
    ap.add_argument("--series", default=None, help="series name (default: first series of the profile)")
    ap.add_argument("--trials", type=int, default=20, help="injections per anomaly type")
    ap.add_argument("--magnitude", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    p = profiles.load(args.profile)
    monthly = aggregate.load_series(p.paths.series)
    name = args.series or next(iter(p.series))
    clean = monthly[name]
    base, _ = detectors.run_detectors(clean)
    base_flags = set(np.flatnonzero(base["anomaly"].to_numpy()))
    rng = np.random.default_rng(args.seed)
    warmup = max(config.BASELINE_WINDOW, config.LSTM_WINDOW) * 3
    candidates = [t for t in range(warmup, len(clean) - 3)
                  if all(abs(t - f) > 3 for f in base_flags)]

    rows = []
    started = time.time()
    for kind in TYPES:
        for t in rng.choice(candidates, size=min(args.trials, len(candidates)), replace=False):
            series, truth = inject(clean, kind, int(t), args.magnitude)
            det, drift = detectors.run_detectors(series)
            row = {"type": kind, "t": int(t), "month": str(clean.index[t])}
            for d in (*detectors.DETECTORS, "ensemble"):
                col = "anomaly" if d == "ensemble" else f"{d}_vote"
                flags = set(np.flatnonzero(det[col].to_numpy()))
                base_d = set(np.flatnonzero(base[col].to_numpy()))
                row[f"{d}_hit"] = bool(flags & set(truth))
                row[f"{d}_new_false"] = len((flags - base_d) - set(range(truth[0], truth[-1] + 13)))
            row["ph_hit"] = any(truth[0] - 2 <= q["alarm_index"] <= truth[0] + 6 for q in drift)
            rows.append(row)
    df = pd.DataFrame(rows)

    summary = {"profile": p.id, "series": name, "months": len(clean),
               "analysis_period": [str(clean.index.min()), str(clean.index.max())],
               "series_file_sha256": hashlib.sha256(p.paths.series.read_bytes()).hexdigest(),
               "trials_per_type": args.trials,
               "magnitude": args.magnitude, "seed": args.seed, "baseline_flags": len(base_flags),
               "seconds": round(time.time() - started, 1), "by_type": {}, "overall": {}}
    for scope, part in [*((k, df[df["type"] == k]) for k in TYPES), ("overall", df)]:
        stats = {}
        for d in (*detectors.DETECTORS, "ensemble"):
            tp = int(part[f"{d}_hit"].sum())
            fp = int(part[f"{d}_new_false"].sum())
            recall = tp / len(part)
            precision = tp / (tp + fp) if tp + fp else 0.0
            stats[d] = {"recall": round(recall, 3), "precision": round(precision, 3),
                        "f1": round(f1(precision, recall), 3), "induced_false_alarms": fp}
        if scope == "level_shift":
            stats["page_hinkley_recall"] = round(float(part["ph_hit"].mean()), 3)
        if scope == "overall":
            summary["overall"] = stats
        else:
            summary["by_type"][scope] = stats

    out = Path(args.out) if args.out else Path(__file__).parent / "results" / f"synthetic_injection_{p.id}_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"{p.id} / {name}: {len(df)} injections, {summary['seconds']}s")
    header = f"{'type':12s}" + "".join(f"{d:>18s}" for d in (*detectors.DETECTORS, "ensemble"))
    print(header + "   (recall / precision)")
    for scope in (*TYPES, "overall"):
        stats = summary["overall"] if scope == "overall" else summary["by_type"][scope]
        cells = "".join(f"{stats[d]['recall']:>10.2f} / {stats[d]['precision']:.2f}" for d in (*detectors.DETECTORS, "ensemble"))
        print(f"{scope:12s}{cells}")
    print(f"Page-Hinkley recall on level shifts: {summary['by_type']['level_shift']['page_hinkley_recall']:.2f}")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
