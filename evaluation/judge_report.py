"""Report on the LLM-as-a-Judge and the human review, from committed results.

Reads results/<profile>/judgments.json and reviews.json (produced by the
GitHub Actions runs) and prints: category distribution, label consistency,
share of invalid answers, latency per call, and human-LLM agreement with a
confusion matrix once stewards have decided.

Usage:
  python evaluation/judge_report.py --profile ibama-autos-infracao
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config, judge, review  # noqa: E402
from src import profile as profiles  # noqa: E402


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=config.DEFAULT_PROFILE)
    args = ap.parse_args(argv)
    p = profiles.load(args.profile)
    judgments = {k: v for k, v in judge.load_judgments(p.paths.judgments).items() if judge.is_current(v)}
    reviews = review.load_reviews(p.paths.reviews)
    if not judgments:
        print(f"No judgments for {p.id} with model {config.LLM_MODEL} / prompt {config.PROMPT_VERSION} yet.")
        return

    df = pd.DataFrame(judgments.values())
    runs = pd.DataFrame([r for j in judgments.values() for r in j["runs"]])
    out = {
        "profile": p.id,
        "model": config.LLM_MODEL,
        "model_digests": sorted({d for d in df["model_digest"].dropna()}),
        "anomalies_judged": len(df),
        "calls": len(runs),
        "invalid_answers": int((runs["category"] == "INVALID").sum()),
        "categories": df["category"].value_counts().to_dict(),
        "mean_consistency": round(float(df["consistency"].mean()), 3),
        "unanimous_rate": round(float((df["consistency"] == 1).mean()), 3),
        "review_levels": df["review_level"].value_counts().to_dict(),
        "latency_s": {k: round(float(v), 1) for k, v in runs["latency_s"].describe()[["mean", "50%", "max"]].items()},
    }
    decided = [(judgments[a]["category"], r["steward_category"]) for a, r in reviews.items()
               if r["status"] == "decided" and a in judgments]
    out["steward_decisions"] = len(decided)
    if decided:
        dd = pd.DataFrame(decided, columns=["llm", "steward"])
        out["human_llm_agreement"] = round(float((dd["llm"] == dd["steward"]).mean()), 3)
        out["confusion_matrix"] = pd.crosstab(dd["llm"], dd["steward"]).to_dict()

    path = Path(__file__).parent / "results" / f"judge_report_{p.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
