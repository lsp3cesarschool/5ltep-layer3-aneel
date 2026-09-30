"""Which LLM judges this run.

LLM_MODEL="auto" (default) follows the model benchmark: its public
recommendation.json has a "use" field, the model it approves for production
(it changes only when a candidate beats the current one by a margin whose paired
confidence interval is above zero). A tag in LLM_MODEL pins the model instead.

Changing the model never invalidates earlier judgments: each one records the
model and prompt version that produced it. Re-judging is a separate, explicit
choice (workflow input `rejudge`).
"""

import logging

import requests

from src import config

logger = logging.getLogger(__name__)


def resolve() -> dict:
    """{"model", "think", "source"} for this run; also applied to src.config."""
    if config.LLM_MODEL != "auto":
        out = {"model": config.LLM_MODEL, "think": config.LLM_THINK, "source": "pinned"}
    else:
        try:
            rec = requests.get(config.MODEL_RECOMMENDATION_URL, timeout=30).json()
            use = rec.get("use")
            if not use:  # recommendation files published before the "use" field
                use = (rec.get("recommended") if rec.get("switch_recommended") else rec.get("production")) or {}
            if not use.get("model"):
                raise ValueError("recommendation without a model")
            think = (use.get("options") or {}).get("think")
            out = {"model": use["model"], "think": config.LLM_THINK or ("" if think is None else str(think).lower()),
                   "source": "benchmark", "benchmark_generated_at": rec.get("generated_at")}
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Model benchmark not readable (%s); using the fallback %s", exc, config.FALLBACK_MODEL)
            out = {"model": config.FALLBACK_MODEL, "think": config.LLM_THINK or config.FALLBACK_THINK,
                   "source": "fallback"}
    config.LLM_MODEL, config.LLM_THINK, config.LLM_MODEL_SOURCE = out["model"], out["think"], out["source"]
    return out
