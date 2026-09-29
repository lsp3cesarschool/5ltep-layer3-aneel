"""Layer 3 summary (input to Layers 4-5) and dashboard data.

L3 pass rate for the Global Quality Score Qs (SOFTENG 2026, Sec. III-E):
over the last L3_WINDOW_MONTHS complete months, each (series, month) pair
passes unless it is flagged by the ensemble AND is either
  - not judged yet,
  - classified as DQE/INVALID (by the steward when decided, else by the LLM), or
  - waiting for a mandatory steward review.
l3_rate = passing pairs / all pairs; l3_pass = no failing pair.
The field names l3_pass and anomaly_flags follow the minimal provenance record
of the 5L-TEP paper, so Layer 4 can ingest them as they are.
"""

import json
import platform
import sys
from datetime import datetime, timezone
from importlib import metadata

import pandas as pd

from src import __version__, config
from src.judge import DETECTOR_NAMES, anomaly_id, is_current
from src.profile import Profile


def environment() -> dict:
    """Interpreter and package versions, so a result can be re-created."""
    pkgs = {}
    for name in ("pandas", "numpy", "scikit-learn", "torch", "requests"):
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pkgs[name] = None
    return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": pkgs}


def effective(aid: str, judgments: dict, reviews: dict) -> dict:
    r = reviews.get(aid)
    if r and r["status"] == "decided":
        return {"category": r["steward_category"], "decided_by": "steward", "pending_review": False}
    j = judgments.get(aid)
    if not is_current(j):
        return {"category": None, "decided_by": None, "pending_review": False}
    return {"category": j["category"], "decided_by": "llm", "pending_review": j["review_level"] == "mandatory"}


def layer3_score(detections: pd.DataFrame, judgments: dict, reviews: dict) -> dict:
    months = sorted(detections.index.unique())[-config.L3_WINDOW_MONTHS:]
    window = detections[detections.index.isin(months)]
    flags, failing = [], 0
    for month, row in window.iterrows():
        if not row["anomaly"]:
            continue
        eff = effective(anomaly_id(row["series"], month), judgments, reviews)
        fails = eff["category"] is None or eff["category"] in ("DQE", "INVALID") or eff["pending_review"]
        failing += fails
        flags.append({"column": row["series"], "period": str(month), "category": eff["category"],
                      "decided_by": eff["decided_by"], "fails": bool(fails)})
    total = len(window)
    return {
        "window": [str(months[0]), str(months[-1])] if months else None,
        "pairs_evaluated": total,
        "l3_rate": round(1 - failing / total, 4) if total else None,
        "l3_pass": failing == 0,
        "anomaly_flags": flags,
    }


def build_summary(profile: Profile, monthly: pd.DataFrame, detections: pd.DataFrame, drift: dict,
                  judgments: dict, reviews: dict, manifest: dict) -> dict:
    flagged = detections[detections["anomaly"]]
    current_ids = [anomaly_id(s, m) for m, s in zip(flagged.index, flagged["series"])]
    judged = [judgments[a] for a in current_ids if is_current(judgments.get(a))]
    cons = [j["consistency"] for j in judged]
    decided = [r for a, r in reviews.items() if r["status"] == "decided" and a in judgments]
    agree = sum(1 for r in decided if judgments[r["anomaly_id"]]["category"] == r["steward_category"])
    open_levels = pd.Series([r["review_level"] for r in reviews.values() if r["status"] != "decided"], dtype=str)
    return {
        "toolkit": f"5ltep-layer3 v{__version__}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": {"id": profile.id, "title": profile["title"],
                    "filters": profile.get("filters", []), "period": profile.get("period")},
        "source": manifest,
        "series": {name: s["description"] for name, s in profile.series.items()},
        "analysis_period": [str(monthly.index.min()), str(monthly.index.max())],
        "months": int(len(monthly)),
        "method_parameters": config.method_parameters(),
        "environment": environment(),
        "anomalies": {
            "flagged": len(current_ids),
            "by_series": {k: int(v) for k, v in flagged["series"].value_counts().items()},
            "judged": len(judged),
            "pending_judgment": len(current_ids) - len(judged),
            "drift_points": {s: len(p) for s, p in drift.items()},
        },
        "llm": {
            "model": config.LLM_MODEL,
            "model_digest": next((j.get("model_digest") for j in judged if j.get("model_digest")), None),
            "categories": {k: int(v) for k, v in pd.Series([j["category"] for j in judged], dtype=str).value_counts().items()},
            "mean_consistency": round(sum(cons) / len(cons), 3) if cons else None,
            "unanimous_rate": round(sum(c == 1 for c in cons) / len(cons), 3) if cons else None,
        },
        "hitl": {
            "issues": len(reviews),
            "decided": len(decided),
            "open_by_level": {k: int(v) for k, v in open_levels.value_counts().items()},
            "human_llm_agreement": round(agree / len(decided), 3) if decided else None,
        },
        "layer3": layer3_score(detections, judgments, reviews),
    }


def dashboard_data(profile: Profile, monthly: pd.DataFrame, detections: pd.DataFrame, drift: dict,
                   judgments: dict, reviews: dict, summary: dict) -> dict:
    anomalies = []
    for month, row in detections[detections["anomaly"]].iterrows():
        aid = anomaly_id(row["series"], month)
        j = judgments.get(aid) if is_current(judgments.get(aid)) else None
        r = reviews.get(aid)
        majority_run = next((x for x in j["runs"] if x["category"] == j["category"]), None) if j else None
        anomalies.append({
            "id": aid, "series": row["series"], "month": str(month), "value": float(row["value"]),
            "votes": int(row["votes"]), "score": float(row["ensemble_score"]),
            "detectors": [d for d in DETECTOR_NAMES if row[f"{d}_vote"]],
            "near_drift": bool(row["near_drift"]),
            "llm": None if not j else {
                "category": j["category"], "consistency": j["consistency"],
                "review_level": j["review_level"],
                "reasoning": majority_run["reasoning"] if majority_run else None,
                "runs": [x["category"] for x in j["runs"]],
            },
            "review": None if not r else {
                "issue": r["issue"], "url": r["url"], "status": r["status"],
                "steward_category": r["steward_category"],
            },
        })
    anomalies.sort(key=lambda a: a["month"], reverse=True)
    rule = profile.get("exclude")
    return {
        "summary": summary,
        "categories": profile.categories,
        "months": [str(m) for m in monthly.index],
        "series": {c: [float(f"{float(v):.6g}") for v in monthly[c]] for c in profile.series},
        "context": {"excluded": [int(v) for v in monthly["excluded"]],
                    "excluded_label": rule["label"] if rule else "excluded",
                    "missing_key": [int(v) for v in monthly["missing_key"]]},
        "anomalies": anomalies,
        "drift": drift,
        "events": profile.events(),
    }


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def write_index(profiles: list[Profile], path) -> None:
    """docs/data/index.json: the profiles that have dashboard data."""
    items = [{"id": p.id, "title": p["title"]} for p in profiles if p.paths.dashboard.exists()]
    from src.profile import default_id

    write_json(path, {"profiles": items, "default": default_id()})
