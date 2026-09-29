"""Suggest events for the calendar with the LLM, grounded on an online source.

For each year that has anomalies, the "year in <country>" page of Wikipedia
(configurable per profile in "event_sources") is fetched and the LLM is asked
which of its events could have affected the records. Every suggestion must
quote the sentence it comes from; suggestions whose quote is not found in the
source text are discarded, which filters out invented events. Without the
online source (--offline) the LLM answers from memory; those suggestions are
marked origin "llm-memory" and deserve extra care.

Suggestions are appended to the profile's events file with
status "suggested". The steward edits that file: "verified" to confirm,
"rejected" to discard (rejected entries are kept so they are not suggested
again). Unverified suggestions reach the judge flagged as such, and only if
the profile sets "events_include_suggested".
"""

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone

import pandas as pd
import requests

from src import config
from src.ckan_source import USER_AGENT
from src.profile import Profile

logger = logging.getLogger(__name__)

KINDS = ("policy", "political", "external")
MAX_SOURCE_CHARS = 12000

SYSTEM = """You help curate a calendar of events that may explain anomalies in open government data.
{domain}
Only list events with a direct link to how many {records} were produced or recorded, or to their
values: laws and regulations of that sector, changes of federal government or of the agency,
disasters or crises in that sector (e.g. environmental disasters for environmental enforcement),
strikes or shutdowns of public services, pandemics. Never list sports, culture, celebrities, crime,
accidents or foreign visits without such a link. Most years have zero to two such events: an empty
list is a normal answer."""

PROMPT_ONLINE = """The monthly series built from these {records} showed anomalies in: {months}.
Already in the calendar for {year} (do not repeat): {known}.

Below is the list of events of {year} from {source}. Select at most {max_events} events with a direct
link to the {records}. For each, give the month (YYYY-MM), a kind ({kinds}), a short English label,
why it is relevant, a relevance score from 0 to 1, and "evidence": one sentence from the text,
copied exactly, at most 200 characters.

--- SOURCE TEXT ---
{text}
--- END ---"""

PROMPT_OFFLINE = """The monthly series built from these {records} showed anomalies in: {months}.
Already in the calendar for {year} (do not repeat): {known}.

From your own knowledge, list at most {max_events} events of {year} in {country} with a direct link
to the {records}. For each, give the month (YYYY-MM), a kind ({kinds}), a short English label, why it
is relevant, a relevance score from 0 to 1, and "evidence": the law number, decree or other
reference you rely on (at most 200 characters). Do not guess: if you are not sure an event happened
in that month, leave it out."""

MIN_RELEVANCE = 0.6
MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_NAMES = "|".join(MONTHS)
# Dates as they open Wikipedia list items: "25 de janeiro" (pt) or "January 25" (en).
DATE_RE = re.compile(rf"\b(\d{{1,2}}) de ({_MONTH_NAMES})\b|\b({_MONTH_NAMES}) (\d{{1,2}})\b")


def schema() -> dict:
    return {
        "type": "object",
        "properties": {"events": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "month": {"type": "string"},
                "kind": {"type": "string", "enum": list(KINDS)},
                "label": {"type": "string"},
                "relevance": {"type": "string"},
                "relevance_score": {"type": "number"},
                "evidence": {"type": "string"},
            },
            "required": ["month", "kind", "label", "relevance", "relevance_score", "evidence"],
        }}},
        "required": ["events"],
    }


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def grounded(evidence: str, source_text: str, min_chars: int = 25) -> bool:
    """True when the quoted evidence occurs in the source (ignoring accents and punctuation)."""
    ev = _norm(evidence)
    if len(ev) < min_chars:
        return False
    src = _norm(source_text)
    return ev in src or ev[:60] in src


def month_in_source(evidence: str, source_text: str) -> int | None:
    """Calendar month of the quoted sentence, read from the date that precedes it in the source.

    The model sometimes quotes the right sentence under the wrong month; the
    source's own date settles it.
    """
    ev, src = _norm(evidence), _norm(source_text)
    pos = src.find(ev)
    if pos < 0:
        pos = src.find(ev[:60])
    if pos < 0:
        return None
    last = None
    for m in DATE_RE.finditer(src, 0, pos + len(ev[:40])):
        last = m
    if not last:
        return None
    name = last.group(2) or last.group(3)
    return MONTHS[name]


def fetch_wikipedia(lang: str, title: str) -> tuple[str, str] | None:
    """Plain-text 'events' section of a Wikipedia page, and its URL."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    params = {"action": "query", "prop": "extracts", "explaintext": 1, "format": "json",
              "redirects": 1, "titles": title}
    try:
        resp = requests.get(api, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Wikipedia request failed for %s: %s", title, exc)
        return None
    page = next(iter(resp.json()["query"]["pages"].values()))
    text = page.get("extract") or ""
    if not text:
        return None
    # Keep the events section when the page has one (pt: "Eventos", en: "Events").
    m = re.search(r"==\s*(Eventos|Events|Acontecimentos)\s*==(.*?)(\n==\s*[^=]|\Z)", text, re.S)
    body = m.group(2) if m else text
    url = f"https://{lang}.wikipedia.org/wiki/{page['title'].replace(' ', '_')}"
    return body[:MAX_SOURCE_CHARS], url


def _similar(a: str, b: str) -> bool:
    wa, wb = set(_norm(a).split()), set(_norm(b).split())
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def is_known(candidate: dict, events: list[dict]) -> bool:
    return any(e["month"] == candidate["month"] and _similar(e["label"], candidate["label"]) for e in events)


def anomaly_months_by_year(detections: pd.DataFrame) -> dict[int, list[str]]:
    flagged = sorted({str(m) for m in detections[detections["anomaly"]].index})
    by_year: dict[int, list[str]] = {}
    for m in flagged:
        by_year.setdefault(int(m[:4]), []).append(m)
    return by_year


def suggest(profile: Profile, detections: pd.DataFrame, client, online: bool = True,
            years: list[int] | None = None, max_years: int = 8, max_events: int = 3) -> dict:
    """Append suggested events to the profile's events file; returns a summary."""
    events_path = config.ROOT / profile["events_file"]
    calendar = json.loads(events_path.read_text(encoding="utf-8"))
    known = calendar["events"] + profile.events(include_suggested=True)
    by_year = anomaly_months_by_year(detections)
    todo = sorted(years or by_year, reverse=True)[:max_years]
    source_cfg = (profile.get("event_sources") or {}).get("wikipedia")
    model = client.info()
    system = SYSTEM.format(domain=profile["domain"], records=profile["record_label"])
    added, dropped = [], []
    for year in todo:
        months = ", ".join(by_year.get(year, [])) or "none"
        known_year = "; ".join(f"{e['month']} {e['label']}" for e in known if e["month"].startswith(str(year)))
        base = dict(records=profile["record_label"], months=months, year=year, known=known_year or "none",
                    max_events=max_events, kinds=", ".join(KINDS))
        source = None
        if online and source_cfg:
            source = fetch_wikipedia(source_cfg.get("lang", "en"), source_cfg["title"].format(year=year))
        if online and source is None:
            logger.warning("%d: no online source; skipped (use --offline to ask the model alone)", year)
            continue
        if source:
            text, url = source
            prompt = PROMPT_ONLINE.format(**base, source=url, text=text)
        else:
            text, url = "", None
            prompt = PROMPT_OFFLINE.format(**base, country=(profile.get("country") or "the publisher's country"))
        try:
            answer, _ = client.generate(system, prompt, seed=config.LLM_SEEDS[0], schema=schema(),
                                        temperature=0.0, num_ctx=8192)
            items = json.loads(answer).get("events", [])
        except (requests.RequestException, ValueError) as exc:
            logger.warning("%d: model call failed: %s", year, exc)
            continue
        for it in items[:max_events]:
            month = str(it.get("month", ""))[:7]
            evidence = it.get("evidence", "")
            corrected_from = None
            if source and grounded(evidence, text):
                src_month = month_in_source(evidence, text)
                if src_month and month != f"{year}-{src_month:02d}":
                    corrected_from, month = month, f"{year}-{src_month:02d}"
            try:
                score = float(it.get("relevance_score", 0))
            except (TypeError, ValueError):
                score = 0.0
            reason = None
            if not re.fullmatch(rf"{year}-(0[1-9]|1[0-2])", month):
                reason = "month outside the year"
            elif it.get("kind") not in KINDS:
                reason = "unknown kind"
            elif source and not grounded(evidence, text):
                reason = "evidence not found in the source"
            elif score < MIN_RELEVANCE:
                reason = f"relevance {score:.2f} below {MIN_RELEVANCE}"
            elif is_known({"month": month, "label": it.get("label", "")}, known):
                reason = "already in the calendar"
            if reason:
                dropped.append({"year": year, "label": it.get("label"), "reason": reason})
                continue
            entry = {
                "month": month,
                "kind": it["kind"],
                "label": it["label"].strip(),
                "source": f"{url} (Wikipedia)" if url else "model knowledge, not checked",
                "evidence": it.get("evidence", "").strip(),
                "relevance": it.get("relevance", "").strip(),
                "relevance_score": round(score, 2),
                "status": "suggested",
                "origin": "llm+wikipedia" if url else "llm-memory",
                "suggested_by": model.get("model"),
                "model_digest": model.get("model_digest"),
                "suggested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if corrected_from:
                entry["month_corrected_from"] = corrected_from  # model's month; the source's date prevails
            calendar["events"].append(entry)
            known.append(entry)
            added.append(entry)
        logger.info("%d: %d suggested so far, %d dropped so far", year, len(added), len(dropped))
    calendar["events"].sort(key=lambda e: e["month"])
    events_path.write_text(json.dumps(calendar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"years": todo, "added": added, "dropped": dropped}
