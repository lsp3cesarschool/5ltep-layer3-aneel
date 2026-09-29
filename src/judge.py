"""Stage 2 of 5L-TEP Layer 3: LLM-as-a-Judge.

A local model served by Ollama reads each candidate anomaly in context and
assigns one category of the profile's taxonomy. Each anomaly is judged
LLM_RUNS times with fixed seeds; the majority label is kept and the share of
runs that agree with it is the label consistency C. Judgments are cached per
profile, so a run only spends inference time on anomalies that have no
judgment yet for the current model and prompt version.
"""

import hashlib
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from src import config
from src.profile import Profile

logger = logging.getLogger(__name__)

DETECTOR_NAMES = ("zscore", "mad", "iforest", "lstm_ed")

SYSTEM_PROMPT = """You are a data-quality analyst reviewing open government data.
{domain}

A statistical ensemble flagged one month of a monthly time series built from these
{records} as anomalous. Decide which category best explains the anomaly:

{categories}

Reason in this order, using only the evidence given:
1. Seasonality. Look at the same calendar month in the previous years. If it usually
   deviates in the same direction (even when this year is stronger), and above all if the
   same calendar month was flagged in other years too, the anomaly is seasonal.
2. Events. If a listed event plausibly explains the timing and the direction, the anomaly
   is policy-driven. Currency reforms only explain changes in monetary values.
3. Records. Signs of a data problem are: a burst of {excluded} or of records without an
   identifier; an abrupt step that persists with no event to explain it (e.g. a change
   of information system); values that are implausible, such as zero or near zero in an
   otherwise active series.
4. Otherwise, a real change that none of the above explains is a genuine shift.
Do not choose the data-quality category only because the deviation is large: a large
deviation is the reason the month was flagged in the first place.

Answer in JSON with: "reasoning" (at most 120 words, step by step), "category" (one of
{codes}) and "confidence" (0 to 1)."""


def response_schema(profile: Profile) -> dict:
    return {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "category": {"type": "string", "enum": list(profile.categories)},
            "confidence": {"type": "number"},
        },
        "required": ["reasoning", "category", "confidence"],
    }


def system_prompt(profile: Profile) -> str:
    rule = profile.get("exclude")
    return SYSTEM_PROMPT.format(
        domain=profile["domain"],
        records=profile["record_label"],
        categories="\n".join(f"- {k}: {v}" for k, v in profile.categories.items()),
        excluded=rule["description"] if rule else "excluded records",
        codes=", ".join(profile.categories),
    )


def _fmt(v: float) -> str:
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f}M"
    if abs(v) >= 1 or v == 0:
        return f"{v:,.0f}"
    return f"{v:.3g}"


def trailing_ratio(values: pd.Series) -> pd.Series:
    """Each month divided by the median of its previous 12 months."""
    base = values.shift(1).rolling(12, min_periods=12).median()
    return values / base.replace(0, np.nan)


def same_month_history(values: pd.Series, month: pd.Period, years: int = 10) -> list[tuple[str, float]]:
    """Trailing ratio of the same calendar month in each of the previous `years` years."""
    ratio = trailing_ratio(values)
    out = []
    for y in range(1, years + 1):
        m = month - 12 * y
        if m in ratio.index and pd.notna(ratio.loc[m]):
            out.append((str(m), round(float(ratio.loc[m]), 2)))
    return out


def events_near(events: list[dict], month: pd.Period, window: int) -> list[dict]:
    near = []
    for ev in events:
        gap = (pd.Period(ev["month"], freq="M") - month).n
        if abs(gap) <= window:
            near.append({**ev, "offset_months": gap})
    return near


def build_prompt(profile: Profile, series_name: str, month: pd.Period, monthly: pd.DataFrame,
                 det_row: pd.Series, other_flagged: list[str], events: list[dict],
                 same_month_flagged: list[str] | None = None) -> str:
    """User prompt with the evidence for one anomaly."""
    k = config.CONTEXT_MONTHS
    window = monthly[(monthly.index >= month - k) & (monthly.index <= month + k)]
    col = monthly[series_name]
    baseline = col[(col.index >= month - 12) & (col.index < month)]
    value = float(col.loc[month])
    base_med = float(baseline.median()) if len(baseline) else float("nan")
    change = f"{(value / base_med - 1) * 100:+.0f}%" if base_med else "n/a"
    ratio_now = value / base_med if base_med else float("nan")
    history = same_month_history(col, month)
    same_dir = sum(1 for _, r in history if (r < 1) == (ratio_now < 1))
    flagged_years = [m for m in (same_month_flagged or []) if m != str(month)]
    votes = [d for d in DETECTOR_NAMES if det_row[f"{d}_vote"]]
    rule = profile.get("exclude")
    excluded_label = rule["label"] if rule else "excluded"
    series_cols = list(profile.series)

    lines = [
        f"Series: {series_name} - {profile.series[series_name]['description']}.",
        f"Anomalous month: {month} (calendar month {month.month}).",
        f"Value: {_fmt(value)}; median of the previous 12 months: {_fmt(base_med)} ({change}; ratio {ratio_now:.2f}).",
        f"Seasonality check - ratio of calendar month {month.month} to the median of its previous 12 months,"
        " in the previous years: " + (" | ".join(f"{m}: {r:.2f}" for m, r in history) if history else "n/a") + ".",
        f"The same calendar month deviated in the same direction ({'below' if ratio_now < 1 else 'above'} 1)"
        f" in {same_dir} of these {len(history)} years.",
        "The same calendar month was also flagged as anomalous in: "
        + (", ".join(flagged_years) if flagged_years else "no other year") + ".",
        f"Detectors that flagged it: {', '.join(votes)} ({int(det_row['votes'])} of 4); "
        f"ensemble score {float(det_row['ensemble_score']):.2f} (0.5 = at threshold).",
        "A Page-Hinkley test found a sustained level shift within "
        f"{config.DRIFT_TOLERANCE_MONTHS} months: " + ("yes." if det_row["near_drift"] else "no."),
        "Other series flagged in the same month: " + (", ".join(other_flagged) if other_flagged else "none") + ".",
        "",
        f"Monthly context (+-{k} months). {excluded_label} = {rule['description'] if rule else 'excluded records'}; "
        "no_id = records without an identifier.",
        "month   | " + " | ".join(series_cols) + f" | {excluded_label} | no_id",
    ]
    for m, row in window.iterrows():
        cells = [_fmt(float(row[c])) for c in series_cols]
        mark = "  <== anomaly" if m == month else ""
        lines.append(f"{m} | " + " | ".join(cells) + f" | {int(row['excluded'])} | {int(row['missing_key'])}{mark}")
    near = events_near(events, month, config.EVENT_WINDOW_MONTHS)
    lines.append("")
    if near:
        lines.append(f"Known events within +-{config.EVENT_WINDOW_MONTHS} months:")
        lines += [f"- {e['month']} ({e['offset_months']:+d} months, {e['kind']}): {e['label']}"
                  + (" [unverified suggestion]" if e.get("status") == "suggested" else "") for e in near]
    else:
        lines.append(f"No known events within +-{config.EVENT_WINDOW_MONTHS} months.")
    return "\n".join(lines)


class OllamaClient:
    def __init__(self, url: str = config.OLLAMA_URL, model: str = config.LLM_MODEL):
        self.url = url.rstrip("/")
        self.model = model

    def info(self) -> dict:
        """Model digest and server version, recorded for provenance."""
        out = {"model": self.model}
        try:
            out["ollama_version"] = requests.get(f"{self.url}/api/version", timeout=10).json().get("version")
            for t in requests.get(f"{self.url}/api/tags", timeout=10).json().get("models", []):
                if self.model in (t.get("name"), t.get("model")):
                    out["model_digest"] = t.get("digest")
                    out["quantization"] = t.get("details", {}).get("quantization_level")
        except requests.RequestException as exc:
            logger.warning("Could not read Ollama info: %s", exc)
        return out

    def generate(self, system: str, prompt: str, seed: int, schema: dict,
                 temperature: float | None = None, num_ctx: int | None = None) -> tuple[str, float]:
        payload = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {
                "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
                "seed": seed,
                "num_predict": config.LLM_NUM_PREDICT if num_ctx is None else 2048,
                "num_ctx": num_ctx or config.LLM_NUM_CTX,
            },
        }
        t0 = time.monotonic()
        resp = requests.post(f"{self.url}/api/generate", json=payload, timeout=config.LLM_TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()["response"], time.monotonic() - t0


def parse_response(text: str, categories: dict) -> dict:
    """Parse one model answer; invalid answers are kept and labelled INVALID."""
    try:
        data = json.loads(text)
        cat = str(data.get("category", "")).strip().upper()
        if cat not in categories:
            raise ValueError(f"unknown category {cat!r}")
        conf = float(data.get("confidence", 0))
        return {"category": cat, "confidence": round(min(max(conf, 0.0), 1.0), 3),
                "reasoning": str(data.get("reasoning", "")).strip()}
    except (ValueError, TypeError, AttributeError) as exc:
        return {"category": "INVALID", "confidence": 0.0, "reasoning": f"Unparseable answer ({exc}): {text[:300]}"}


def aggregate_runs(runs: list[dict]) -> dict:
    """Majority vote over runs; ties go to the label with higher mean confidence."""
    valid = [r for r in runs if r["category"] != "INVALID"]
    if not valid:
        return {"category": "INVALID", "consistency": 0.0}
    counts = Counter(r["category"] for r in valid)
    top = max(counts.values())
    tied = [c for c, n in counts.items() if n == top]
    winner = max(tied, key=lambda c: np.mean([r["confidence"] for r in valid if r["category"] == c]))
    return {"category": winner, "consistency": round(top / len(runs), 3)}


def review_level(category: str, consistency: float, near_drift: bool = False) -> str:
    """Human-in-the-loop protocol.

    - mandatory: data-quality events (and invalid answers): no action before a steward decides;
    - advisory: inconsistent labels, and anomalies next to a sustained level shift
      (Page-Hinkley), because the 5L-TEP paper routes confirmed drift to a review of the
      data's structure whatever its cause;
    - none: everything else.
    """
    if category in ("DQE", "INVALID"):
        return "mandatory"
    if consistency < config.ADVISORY_CONSISTENCY or near_drift:
        return "advisory"
    return "none"


def apply_review_policy(judgments: dict) -> int:
    """Recompute review levels from stored judgments (policy only, no LLM call)."""
    changed = 0
    for j in judgments.values():
        level = review_level(j["category"], j["consistency"], j.get("near_drift", False))
        if j.get("review_level") != level:
            j["review_level"] = level
            changed += 1
    return changed


def anomaly_id(series_name: str, month) -> str:
    return f"{series_name}:{month}"


def load_judgments(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_judgments(judgments: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(judgments.items())), ensure_ascii=False, indent=1), encoding="utf-8")


def is_current(entry: dict | None, model: str = config.LLM_MODEL) -> bool:
    return bool(entry) and entry.get("model") == model and entry.get("prompt_version") == config.PROMPT_VERSION


def data_fingerprint(monthly: pd.DataFrame, month: pd.Period) -> str:
    """SHA-256 of the data that make a month anomalous: that month and the 12 before it.

    Later months are deliberately left out, so an anomaly judged once is not
    judged again just because time has passed; only a change in its own data
    (e.g. a retroactive correction in the portal) triggers a new judgment.
    """
    rows = monthly[(monthly.index >= month - 12) & (monthly.index <= month)]
    return hashlib.sha256(rows.to_csv(float_format="%.10g").encode()).hexdigest()


def needs_judgment(entry: dict | None, model: str, fingerprint: str) -> bool:
    if not is_current(entry, model):
        return True
    known = entry.get("data_fingerprint")
    return known is not None and known != fingerprint


def judge_pending(profile: Profile, monthly: pd.DataFrame, detections: pd.DataFrame, client,
                  max_judgments: int = config.MAX_JUDGMENTS,
                  max_minutes: float = config.MAX_JUDGE_MINUTES) -> dict:
    """Judge flagged anomalies without a current judgment, most recent first."""
    path = profile.paths.judgments
    judgments = load_judgments(path)
    model_info = client.info()
    events = profile.events()
    system = system_prompt(profile)
    schema = response_schema(profile)
    flagged = detections[detections["anomaly"]]
    flagged_by_month: dict = {}
    for m, s in zip(flagged.index, flagged["series"]):
        flagged_by_month.setdefault(m, []).append(s)
    pending, backfilled = [], 0
    for m, row in flagged.iterrows():
        aid = anomaly_id(row["series"], m)
        fp = data_fingerprint(monthly, m)
        entry = judgments.get(aid)
        if needs_judgment(entry, client.model, fp):
            pending.append((m, row, fp))
        elif "data_fingerprint" not in entry:
            entry["data_fingerprint"] = fp  # judged before fingerprints existed
            backfilled += 1
    if backfilled:
        save_judgments(judgments, path)
    pending.sort(key=lambda item: item[0], reverse=True)
    logger.info("%d anomalies flagged, %d already judged on the same data, %d pending judgment",
                len(flagged), len(flagged) - len(pending), len(pending))

    deadline = time.monotonic() + max_minutes * 60
    done = 0
    for month, row, fp in pending:
        if done >= max_judgments or time.monotonic() > deadline:
            break
        others = [s for s in flagged_by_month[month] if s != row["series"]]
        same_month = [str(m) for m in flagged[flagged["series"] == row["series"]].index if m.month == month.month]
        prompt = build_prompt(profile, row["series"], month, monthly, row, others, events, same_month)
        runs = []
        for seed in config.LLM_SEEDS[: config.LLM_RUNS]:
            try:
                text, latency = client.generate(system, prompt, seed, schema)
                parsed = parse_response(text, profile.categories)
            except requests.RequestException as exc:
                latency, parsed = 0.0, {"category": "INVALID", "confidence": 0.0, "reasoning": f"Request failed: {exc}"}
            parsed.update({"seed": seed, "latency_s": round(latency, 1)})
            runs.append(parsed)
        vote = aggregate_runs(runs)
        aid = anomaly_id(row["series"], month)
        previous = judgments.get(aid)
        history = []
        if previous:
            history = previous.get("history", []) + [
                {k: previous.get(k) for k in ("category", "consistency", "model", "prompt_version",
                                              "data_fingerprint", "judged_at")}]
        reason = None
        if previous:
            reason = ("data changed" if is_current(previous, client.model)
                      else "model or prompt version changed")
        judgments[aid] = {
            "series": row["series"],
            "month": str(month),
            "category": vote["category"],
            "consistency": vote["consistency"],
            "review_level": review_level(vote["category"], vote["consistency"], bool(row["near_drift"])),
            "ensemble_score": float(row["ensemble_score"]),
            "votes": int(row["votes"]),
            "near_drift": bool(row["near_drift"]),
            "runs": runs,
            "prompt": prompt,
            "model": client.model,
            "model_digest": model_info.get("model_digest"),
            "ollama_version": model_info.get("ollama_version"),
            "temperature": config.LLM_TEMPERATURE,
            "prompt_version": config.PROMPT_VERSION,
            "data_fingerprint": fp,
            "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if reason:
            judgments[aid]["rejudge_reason"] = reason
            judgments[aid]["history"] = history
        done += 1
        save_judgments(judgments, path)  # persist after each anomaly: a timeout loses nothing
        logger.info("[%d] %s -> %s (C=%.2f)", done, aid, vote["category"], vote["consistency"])
    return {"judged_now": done, "pending_before": len(pending), "model": model_info}
