"""Safety checks between untrusted inputs and the repository.

Threat model (see SECURITY.md): the LLM, its weights and the open data portal are not trusted.
A model can be malicious or tampered with (for example, tuned to pass the public benchmark and
behave differently on other inputs), and its output is text written by that model. So:

- model names that reach a shell or $GITHUB_ENV must match a strict pattern;
- the job that runs the model has a read-only token and hands its results over as an artifact;
  the job that writes to the repository accepts only the expected files, with the expected
  structure and bounded sizes (`accept_artifact`), and never runs the model;
- text written by the model is bounded and neutralised before it goes into a GitHub Issue
  (`safe_markdown`); the dashboard escapes everything it shows.
"""

import json
import re
import shutil
from pathlib import Path

import pandas as pd

# Ollama tags (e.g. qwen3:4b, gemma3:4b-it-q4_K_M, namespace/model:tag) and GGUF/Hugging Face names.
MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}(/[a-z0-9][a-z0-9._-]{0,63})?(:[A-Za-z0-9][A-Za-z0-9._-]{0,63})?$")
DIGEST_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$")
THINK_VALUES = {"", "true", "false"}

MAX_REASONING = 2000      # characters kept from one answer of the model
MAX_TRANSLATION = 6000    # characters of one translation
MAX_FILE_BYTES = 80_000_000      # per result file; GitHub refuses files above 100 MB


def valid_model(name: str) -> bool:
    return isinstance(name, str) and bool(MODEL_RE.match(name))


def valid_digest(digest: str | None) -> bool:
    return digest in (None, "") or (isinstance(digest, str) and bool(DIGEST_RE.match(digest)))


def clean_text(text, limit: int) -> str:
    """Model text as data: no control characters (newlines and tabs kept), bounded length."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]", "", str(text or ""))
    return text if len(text) <= limit else text[:limit] + " […]"


def safe_markdown(text, limit: int = MAX_REASONING) -> str:
    """Model text inside a GitHub Issue: no HTML, links, images, mentions, references or tables."""
    text = clean_text(text, limit).replace("\r", " ").replace("\n", " ")
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("|", "/").replace("`", "'"))
    text = re.sub(r"!?\[([^\]]*)\]\(([^)]*)\)", r"\1 (\2)", text)          # links and images
    text = re.sub(r"(?<![\w`])@(?=\w)", "@​", text)                      # no @mentions
    text = re.sub(r"(?<![\w&])#(?=\d)", "#​", text)                      # no #123 references
    text = re.sub(r"https?://", lambda m: m.group(0).replace("://", ":​//"), text)  # no autolinks
    return text


# ---------------------------------------------------------------------------------------------
# Hand-over from the job that runs the model (read-only) to the job that writes (no model).

def _allowed(profile_id: str) -> dict:
    return {
        f"data/{profile_id}/monthly_series.csv": "csv",
        f"data/{profile_id}/source_manifest.json": "json",
        f"results/{profile_id}/detections.csv": "csv",
        f"results/{profile_id}/drift_points.json": "json",
        f"results/{profile_id}/judgments.json": "judgments",
        f"results/{profile_id}/translations.json": "translations",
        f"results/{profile_id}/run_log.jsonl": "jsonl",
    }


def _check_judgments(data: dict, categories: set) -> None:
    if not isinstance(data, dict):
        raise ValueError("judgments: not an object")
    for aid, j in data.items():
        if not re.match(r"^[\w.-]{1,64}:\d{4}-\d{2}$", str(aid)):
            raise ValueError(f"judgments: unexpected anomaly id {aid!r}")
        for entry in [j, *j.get("history", [])]:
            if "category" in entry and entry["category"] not in categories | {"INVALID"}:
                raise ValueError(f"judgments: unknown category in {aid}")
            if "model" in entry and entry["model"] and not valid_model(entry["model"]):
                raise ValueError(f"judgments: unexpected model name in {aid}")
            for run in entry.get("runs", []):
                if run.get("category") not in categories | {"INVALID"}:
                    raise ValueError(f"judgments: unknown category in a run of {aid}")
                if len(str(run.get("reasoning", ""))) > MAX_REASONING + 400:
                    raise ValueError(f"judgments: reasoning too long in {aid}")


def _check_translations(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("translations: not an object")
    for lang, table in data.items():
        if lang not in ("pt",) or not isinstance(table, dict):
            raise ValueError(f"translations: unexpected language {lang!r}")
        for key, entry in table.items():
            if not re.match(r"^[0-9a-f]{64}$", key) or not isinstance(entry, dict):
                raise ValueError("translations: unexpected entry")
            if not isinstance(entry.get("text"), str) or len(entry["text"]) > MAX_TRANSLATION:
                raise ValueError("translations: text missing or too long")


def accept_artifact(src: Path, root: Path, profile_id: str, categories: set) -> list[str]:
    """Validate the files handed over by the analysis job and copy them into the repository.

    Anything else in the artifact (other paths, scripts, workflow files) is refused: the
    analysis job can only ever change this profile's data and results.
    """
    allowed = _allowed(profile_id)
    found = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    unexpected = [f for f in found if f not in allowed and f != "chain.json"]
    if unexpected:
        raise ValueError(f"artifact contains unexpected files: {unexpected[:5]}")
    accepted = []
    for rel in found:
        if rel == "chain.json":
            continue
        path = src / rel
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"{rel}: too large")
        kind = allowed[rel]
        if kind == "csv":
            pd.read_csv(path, nrows=5)
        elif kind == "jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if kind == "judgments":
                _check_judgments(data, categories)
            elif kind == "translations":
                _check_translations(data)
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        accepted.append(rel)
    return accepted


def read_chain(src: Path) -> dict:
    """State the analysis job passes on (anomalies still pending, start of a re-judge chain)."""
    path = src / "chain.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    before = str(raw.get("rejudge_before") or "")
    return {"pending_after": int(raw.get("pending_after") or 0),
            "rejudge_before": before if re.match(r"^[\d:T+.-]{0,40}$", before) else ""}


# ---------------------------------------------------------------------------------------------
# Event suggestions: the LLM proposes, a pull request carries them, a person decides.

EVENT_KEYS = {"month", "kind", "label", "source", "evidence", "relevance", "relevance_score", "status",
              "origin", "suggested_by", "model_digest", "suggested_at", "month_corrected_from"}
SOURCE_RE = re.compile(r"^(https://[a-z]{2,3}\.wikipedia\.org/wiki/[^\s<>\"']{1,200} \(Wikipedia\)|model knowledge, not checked)$")


def check_events_update(old: dict, new: dict) -> list[dict]:
    """The suggestion job may only append entries marked "suggested" to the calendar; everything
    already in it stays exactly as it was. Returns the appended entries."""
    if not isinstance(new, dict) or not isinstance(new.get("events"), list):
        raise ValueError("events: not a calendar")
    if {k: v for k, v in new.items() if k != "events"} != {k: v for k, v in old.items() if k != "events"}:
        raise ValueError("events: the calendar's other fields changed")
    before = old.get("events", [])
    if new["events"][:len(before)] != before:
        raise ValueError("events: existing entries were changed or removed")
    added = new["events"][len(before):]
    for e in added:
        if not isinstance(e, dict) or set(e) - EVENT_KEYS:
            raise ValueError(f"events: unexpected fields {sorted(set(e) - EVENT_KEYS) if isinstance(e, dict) else e}")
        if e.get("status") != "suggested" or e.get("origin") not in ("llm+wikipedia", "llm-memory"):
            raise ValueError("events: a new entry must be a suggestion")
        if not re.match(r"^\d{4}-\d{2}$", str(e.get("month", ""))) or e.get("kind") not in ("policy", "political", "external"):
            raise ValueError("events: bad month or kind")
        if not SOURCE_RE.match(str(e.get("source", ""))):
            raise ValueError("events: unexpected source")
        for key, limit in (("label", 300), ("evidence", 600), ("relevance", 600)):
            if not isinstance(e.get(key, ""), str) or len(e.get(key, "")) > limit or clean_text(e.get(key, ""), limit) != e.get(key, ""):
                raise ValueError(f"events: {key} too long or with control characters")
        if not isinstance(e.get("relevance_score", 0), (int, float)) or not 0 <= e.get("relevance_score", 0) <= 1:
            raise ValueError("events: bad relevance score")
        if e.get("suggested_by") and not valid_model(e["suggested_by"]):
            raise ValueError("events: bad model name")
        if not valid_digest(e.get("model_digest")):
            raise ValueError("events: bad model digest")
    return added
