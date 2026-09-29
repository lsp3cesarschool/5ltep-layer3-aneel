"""Method parameters shared by every profile.

What is analysed (portal, dataset, columns, cut, series, domain text, event
calendar, category taxonomy) lives in a profile under profiles/. What is
configured here is *how* it is analysed. Every value is overridable by an
environment variable of the same name, so a GitHub Actions run can be tuned
without code changes; the values actually used are recorded in each run's
summary.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = ROOT / "profiles"
# Profile used when none is named: the PROFILE variable, else the first
# profile marked "scheduled" (see src/profile.py), so an instance for another
# portal needs no code change.
DEFAULT_PROFILE = os.environ.get("PROFILE") or None


def _env(name: str, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return type(default)(raw)


# --- Detectors (5L-TEP Layer 3, stage 1) -----------------------------------
BASELINE_WINDOW = _env("BASELINE_WINDOW", 12)      # rolling baseline, periods
ZSCORE_K = _env("ZSCORE_K", 3.0)                    # k-sigma rule (SOFTENG: k=3)
MAD_K = _env("MAD_K", 3.0)                          # modified z-score threshold
IF_CONTAMINATION = _env("IF_CONTAMINATION", 0.05)   # Isolation Forest alpha
LSTM_WINDOW = _env("LSTM_WINDOW", 12)
LSTM_UNITS = _env("LSTM_UNITS", 64)
LSTM_DROPOUT = _env("LSTM_DROPOUT", 0.2)
LSTM_EPOCHS = _env("LSTM_EPOCHS", 60)
LSTM_PERCENTILE = _env("LSTM_PERCENTILE", 99.0)     # threshold on reconstruction errors
ENSEMBLE_MIN_VOTES = _env("ENSEMBLE_MIN_VOTES", 2)  # flag if >=2 of 4 agree
PH_DELTA = _env("PH_DELTA", 0.5)                    # Page-Hinkley tolerance (noise units)
PH_LAMBDA = _env("PH_LAMBDA", 12.0)                 # Page-Hinkley alarm threshold
DRIFT_TOLERANCE_MONTHS = _env("DRIFT_TOLERANCE_MONTHS", 2)
RANDOM_SEED = _env("RANDOM_SEED", 42)

# --- LLM-as-a-Judge (stage 2) ------------------------------------------------
OLLAMA_URL = _env("OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = _env("LLM_MODEL", "gemma3:4b")
LLM_RUNS = _env("LLM_RUNS", 3)
# T=0 would make the three runs identical by construction, so consistency
# would measure nothing. We sample at T>0 with fixed seeds instead: the runs
# can disagree, yet every run is reproducible.
LLM_TEMPERATURE = _env("LLM_TEMPERATURE", 0.7)
LLM_SEEDS = [int(s) for s in _env("LLM_SEEDS", "11,22,33").split(",")]
LLM_NUM_PREDICT = _env("LLM_NUM_PREDICT", 400)
LLM_NUM_CTX = _env("LLM_NUM_CTX", 4096)
LLM_TIMEOUT_S = _env("LLM_TIMEOUT_S", 600)
CONTEXT_MONTHS = _env("CONTEXT_MONTHS", 12)          # +-12 months around the anomaly
EVENT_WINDOW_MONTHS = _env("EVENT_WINDOW_MONTHS", 6)  # events within +-6 months
# Bump when the evidence given to the judge changes meaning; every anomaly is
# then judged once more and the previous judgment moves to its history.
# v2: fines converted to Reais, unverified events flagged, significant digits;
#     year-by-year seasonality evidence and symmetric criteria (v1 labelled
#     recurring January drops as data-quality events).
PROMPT_VERSION = "v2"
# Budget per run: CPU inference on the Actions runner is slow, so each run
# judges at most this many new anomalies (most recent first) and stops early
# when the time budget runs out. The next run continues where it stopped.
MAX_JUDGMENTS = _env("MAX_JUDGMENTS", 25)
MAX_JUDGE_MINUTES = _env("MAX_JUDGE_MINUTES", 240.0)

# --- Human-in-the-loop review (GitHub Issues) --------------------------------
ADVISORY_CONSISTENCY = _env("ADVISORY_CONSISTENCY", 0.6)  # below this: advisory review
MAX_NEW_ISSUES = _env("MAX_NEW_ISSUES", 15)
ISSUE_LABEL = "layer3"
STEWARD_LABEL_PREFIX = "steward:"

# --- Layer 3 score for the Global Quality Score (Qs) -------------------------
L3_WINDOW_MONTHS = _env("L3_WINDOW_MONTHS", 12)


def method_parameters() -> dict:
    """Snapshot of the parameters above, stored with every result."""
    names = [
        "BASELINE_WINDOW", "ZSCORE_K", "MAD_K", "IF_CONTAMINATION", "LSTM_WINDOW", "LSTM_UNITS",
        "LSTM_DROPOUT", "LSTM_EPOCHS", "LSTM_PERCENTILE", "ENSEMBLE_MIN_VOTES", "PH_DELTA",
        "PH_LAMBDA", "DRIFT_TOLERANCE_MONTHS", "RANDOM_SEED", "LLM_MODEL", "LLM_RUNS",
        "LLM_TEMPERATURE", "LLM_SEEDS", "LLM_NUM_PREDICT", "LLM_NUM_CTX", "CONTEXT_MONTHS",
        "EVENT_WINDOW_MONTHS", "PROMPT_VERSION", "ADVISORY_CONSISTENCY", "L3_WINDOW_MONTHS",
    ]
    return {n.lower(): globals()[n] for n in names}
