"""Compare the model in use with the recommendation of the model benchmark.

The benchmark (5ltep-layer3-modeltest) publishes results/recommendation.json.
This reads it over plain HTTPS (no token crosses repositories) and, when a
switch is recommended for a model other than the one in use, opens one issue
in this repository (or comments on the open one if the recommendation changed).
Switching stays a human decision: set the repository variable LLM_MODEL (and
LLM_THINK when the recommendation says so); every anomaly is then judged again
and its previous judgment kept in its history.
"""

import json
import logging

import requests

from src import config

logger = logging.getLogger(__name__)

MARKER = "<!-- l3-model-recommendation -->"
LABEL = "model-recommendation"


def fetch(url: str = config.MODEL_RECOMMENDATION_URL) -> dict:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def decide(rec: dict, current_model: str) -> dict:
    best = rec.get("recommended") or {}
    if not rec.get("switch_recommended") or not best:
        return {"action": "none", "why": rec.get("reason", "no recommendation")}
    if best.get("model") == current_model:
        return {"action": "none", "why": f"{current_model} is already in use"}
    return {"action": "propose", "why": rec.get("reason", ""), "model": best["model"], "backend": best.get("backend")}


def issue_body(rec: dict, current_model: str) -> str:
    best = rec["recommended"]
    think = (best.get("options") or {}).get("think")
    steps = [f"Set the repository variable `LLM_MODEL` to `{best['model']}` "
             "(*Settings → Secrets and variables → Actions → Variables*)."]
    if think is not None:
        steps.append(f"Set the repository variable `LLM_THINK` to `{str(think).lower()}`.")
    if best.get("backend") != "ollama":
        steps.insert(0, f"Note: the winner runs on **{best.get('backend')}**, not Ollama; production would need "
                        "that back-end first.")
    steps.append("Run *Actions → 5L-TEP Layer 3 Anomaly Detection → Run workflow*: every anomaly is judged "
                 "again with the new model, in batches; previous judgments stay in each anomaly's history.")
    prod = rec.get("production") or {}
    return f"""{MARKER}
The [model benchmark]({rec.get('benchmark')}) recommends switching the LLM-as-a-Judge.

| | In use | Recommended |
|---|---|---|
| Model | `{current_model}` | `{best['model']}` ({best.get('backend')}) |
| macro-F1 on the gold set | {prod.get('macro_f1', '–')} | **{best.get('macro_f1')}** {best.get('macro_f1_ci95', '')} |
| Label consistency | {prod.get('consistency', '–')} | {best.get('consistency')} |
| p90 latency per call | {prod.get('latency_p90_s', '–')} s | {best.get('latency_p90_s')} s |

{rec.get('reason', '')}. Gold set: {rec.get('gold_cases')} cases; production prompt at `{(rec.get('prompt_commit') or '')[:7]}`.

### If you agree
""" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) + """

Close this issue if you prefer to keep the current model.

<details><summary>Recommendation file</summary>

```json
""" + json.dumps(rec, indent=1) + """
```
</details>
"""


def run(gh, current_model: str = config.LLM_MODEL) -> dict:
    rec = fetch()
    d = decide(rec, current_model)
    logger.info("Model check: %s (%s)", d["action"], d["why"])
    if d["action"] != "propose":
        return d
    open_issues = [i for i in gh._req("GET", "/issues", params={"labels": LABEL, "state": "open", "per_page": 100})
                   if MARKER in (i.get("body") or "")]
    body = issue_body(rec, current_model)
    title = f"[L3] Model benchmark recommends {rec['recommended']['model']} instead of {current_model}"
    if open_issues:
        issue = open_issues[0]
        if f"`{rec['recommended']['model']}`" not in (issue.get("body") or ""):
            gh._req("PATCH", f"/issues/{issue['number']}", json={"title": title, "body": body})
            gh.comment(issue["number"], f"The recommendation changed: now `{rec['recommended']['model']}`.")
        return {**d, "issue": issue["number"], "updated": True}
    gh.ensure_labels({LABEL: ("1d76db", "Model benchmark suggests another LLM-as-a-Judge")})
    issue = gh.create_issue(title, body, [LABEL])
    return {**d, "issue": issue["number"], "created": True}
