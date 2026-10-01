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

from src import config, safety

logger = logging.getLogger(__name__)


def resolve() -> dict:
    """{"model", "think", "source", "digest"} for this run; also applied to src.config.

    What comes from the benchmark is checked before use (see src/safety.py): the model name and
    digest must match strict patterns (they reach a shell and $GITHUB_ENV), and only an Ollama
    recommendation can run in production. Anything else falls back to FALLBACK_MODEL.
    """
    if config.LLM_MODEL != "auto":
        if not safety.valid_model(config.LLM_MODEL) or config.LLM_THINK.lower() not in safety.THINK_VALUES:
            raise ValueError(f"LLM_MODEL / LLM_THINK not valid: {config.LLM_MODEL!r} / {config.LLM_THINK!r}")
        out = {"model": config.LLM_MODEL, "think": config.LLM_THINK.lower(), "source": "pinned", "digest": ""}
    else:
        try:
            rec = requests.get(config.MODEL_RECOMMENDATION_URL, timeout=30).json()
            use = rec.get("use")
            if not use:  # recommendation files published before the "use" field
                use = (rec.get("recommended") if rec.get("switch_recommended") else rec.get("production")) or {}
            if not use.get("model"):
                raise ValueError("recommendation without a model")
            if use.get("backend", "ollama") != "ollama":
                raise ValueError(f"recommended back-end {use.get('backend')!r} does not run in production")
            if not safety.valid_model(use["model"]) or not safety.valid_digest(use.get("digest")):
                raise ValueError("recommended model name or digest does not match the expected pattern")
            think = (use.get("options") or {}).get("think")
            think = config.LLM_THINK or ("" if think is None else str(think).lower())
            if think not in safety.THINK_VALUES:
                raise ValueError("recommended think option not valid")
            out = {"model": use["model"], "think": think, "source": "benchmark",
                   "digest": use.get("digest") or "", "benchmark_generated_at": rec.get("generated_at")}
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Model benchmark not readable (%s); using the fallback %s", exc, config.FALLBACK_MODEL)
            out = {"model": config.FALLBACK_MODEL, "think": config.LLM_THINK or config.FALLBACK_THINK,
                   "source": "fallback", "digest": ""}
    config.LLM_MODEL, config.LLM_THINK, config.LLM_MODEL_SOURCE = out["model"], out["think"], out["source"]
    return out
