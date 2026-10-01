"""Machine translation of the texts shown on the dashboard (its Portuguese version).

The LLM-as-a-Judge writes its reasoning in English: the production prompt is in English, and that
is what the model benchmark measures, so the judgment itself never changes language. After each
batch, the same local model translates into Portuguese the texts the dashboard shows that have no
translation yet: the reasoning of each judgment, the event labels and the profile's descriptions.
Translations are stored apart from the judgments, keyed by the SHA-256 of the source text, so a
text is translated once and a judgment is never touched; the dashboard marks them as machine
translations and shows the original on hover.
"""

import hashlib
import json
import logging
import time

from src import config
from src.judge import has_judgment
from src.profile import Profile

logger = logging.getLogger("layer3")

LANGS = ("pt",)
SYSTEM = {
    "pt": (
        "You translate short texts about the quality of open government data from English into "
        "Brazilian Portuguese. Translate everything, titles included. Keep unchanged: category codes "
        "(PDC, SP, DQE, GES, INVALID), numbers, dates such as 2019-01, series names such as notices or "
        "fine_total_brl, and proper names of laws, agencies and places. Do not add, explain or remove "
        "anything. If the text is already in Portuguese, return it as it is."
    ),
}
# Terms the dashboard uses everywhere; profiles/i18n/<profile>.pt.json adds the domain's own terms.
GLOSSARY = {
    "pt": {
        "flagged": "sinalizado(a)", "anomaly": "anomalia", "seasonality check": "verificação de sazonalidade",
        "seasonal pattern": "padrão sazonal", "level shift": "mudança de nível", "data quality": "qualidade de dados",
        "steward": "gestor", "ratio": "razão", "median": "mediana", "detector": "detector",
        "policy-driven change": "mudança por política", "genuine enforcement shift": "mudança genuína de fiscalização",
        "data-quality event": "evento de qualidade de dados", "currency reform": "reforma monetária",
    },
}
SCHEMA = {"type": "object", "properties": {"translation": {"type": "string"}}, "required": ["translation"]}


def system_prompt(profile: Profile, lang: str) -> str:
    """Instructions with the glossary: the general terms plus the profile's own (profiles/i18n/)."""
    own = config.PROFILES_DIR / "i18n" / f"{profile.id}.{lang}.json"  # apart from the profile on purpose
    extra = json.loads(own.read_text(encoding="utf-8")).get("glossary", {}) if own.exists() else {}
    terms = {**GLOSSARY[lang], **extra}
    glossary = "; ".join(f'"{en}" -> "{tr}"' for en, tr in terms.items())
    return f"{SYSTEM[lang]} Always use these translations of terms: {glossary}."


def prompt_version(system: str) -> str:
    """Translations made with other instructions (e.g. an older glossary) are redone."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]


def text_key(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def majority_reasoning(j: dict) -> str | None:
    """The reasoning the dashboard shows: the first run that agrees with the majority label."""
    run = next((x for x in j.get("runs", []) if x["category"] == j["category"]), None)
    return run["reasoning"] if run else None


def dashboard_texts(profile: Profile, judgments: dict) -> list[str]:
    """Every text of the dashboard that comes from the data (the page's own labels are in app.js)."""
    texts = [profile.get("title", "")]
    texts += [s.get("description", "") for s in profile.series.values()]
    texts += list(profile.categories.values())
    rule = profile.get("exclude")
    if rule:
        texts.append(rule.get("label", ""))
    texts += [e.get("label", "") for e in profile.events()]
    texts += [majority_reasoning(j) or "" for j in judgments.values() if has_judgment(j)]
    seen, out = set(), []
    for t in texts:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load(path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {lang: data.get(lang, {}) for lang in LANGS}


def save(store: dict, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


def lookup(store: dict, texts: list[str], lang: str) -> dict:
    """{source text: translation} for the texts that have one (what the dashboard needs)."""
    table = store.get(lang, {})
    return {t: table[text_key(t)]["text"] for t in texts if text_key(t) in table}


def translate_pending(texts: list[str], store: dict, client, path, max_minutes: float,
                      systems: dict | None = None) -> dict:
    """Translate the texts without a current translation (missing, or made with other
    instructions), saving after each one. `systems`: {lang: instructions} (default: no glossary)."""
    systems = systems or SYSTEM
    start, done, failed = time.monotonic(), 0, 0
    for lang in LANGS:
        table = store.setdefault(lang, {})
        version = prompt_version(systems[lang])
        current = lambda x: text_key(x) in table and table[text_key(x)].get("version") == version  # noqa: E731
        for t in texts:
            k = text_key(t)
            if current(t):
                continue
            if time.monotonic() - start > max_minutes * 60:
                logger.info("Translation budget of %.0f min reached", max_minutes)
                return {"translated": done, "failed": failed, "remaining": sum(1 for x in texts if not current(x))}
            try:
                raw, _ = client.generate(systems[lang], t, seed=0, schema=SCHEMA, temperature=0.0)
                out = str(json.loads(raw)["translation"]).strip()
            except Exception as exc:  # one bad answer must not stop the others
                logger.warning("Translation failed (%s): %.60s", exc, t)
                failed += 1
                continue
            if not out:
                failed += 1
                continue
            table[k] = {"text": out, "model": client.model, "version": version}
            save(store, path)
            done += 1
    return {"translated": done, "failed": failed, "remaining": 0}
