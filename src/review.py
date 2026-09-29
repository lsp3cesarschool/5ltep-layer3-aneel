"""Human-in-the-loop review through GitHub Issues.

Every judged anomaly that needs a steward (mandatory: DQE or invalid answers;
advisory: label consistency below the threshold) becomes one issue. The
steward decides by applying exactly one `steward:<CATEGORY>` label and
closing the issue; GitHub keeps who did what and when. `sync_reviews` reads
those decisions back into results/<profile>/reviews.json.

Issues are matched to anomalies through a hidden marker in the body
(`<profile>/<series>:<month>`), so re-running never duplicates an issue.
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import requests

from src import config
from src.profile import Profile

logger = logging.getLogger(__name__)

API = "https://api.github.com"
MARKER = "<!-- l3-anomaly-id: {} -->"
MARKER_RE = re.compile(r"<!-- l3-anomaly-id: (\S+) -->")


def labels_for(profile: Profile) -> dict[str, tuple[str, str]]:
    labels = {
        config.ISSUE_LABEL: ("5319e7", "5L-TEP Layer 3 anomaly review"),
        f"profile:{profile.id}": ("bfd4f2", profile["title"][:100]),
        "review:mandatory": ("d73a4a", "Steward review required before any action"),
        "review:advisory": ("fbca04", "Low LLM label consistency; review recommended"),
    }
    for code, desc in profile.categories.items():
        short = desc.split(":")[0][:80]
        labels[f"llm:{code}"] = ("c5def5", f"LLM-as-a-Judge label: {short}")
        labels[f"{config.STEWARD_LABEL_PREFIX}{code}"] = ("0e8a16", f"Steward decision: {short}")
    return labels


class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    @classmethod
    def from_env(cls) -> "GitHub":
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        if not repo or not token:
            raise RuntimeError("GITHUB_REPOSITORY and GITHUB_TOKEN must be set")
        return cls(repo, token)

    def _req(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, f"{API}/repos/{self.repo}{path}", timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def issues(self) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._req("GET", "/issues", params={
                "labels": config.ISSUE_LABEL, "state": "all", "per_page": 100, "page": page})
            out.extend(i for i in batch if "pull_request" not in i)
            if len(batch) < 100:
                return out
            page += 1

    def ensure_labels(self, wanted: dict[str, tuple[str, str]]) -> None:
        existing, page = set(), 1
        while True:
            batch = self._req("GET", "/labels", params={"per_page": 100, "page": page})
            existing |= {lbl["name"] for lbl in batch}
            if len(batch) < 100:
                break
            page += 1
        for name, (color, desc) in wanted.items():
            if name not in existing:
                self._req("POST", "/labels", json={"name": name, "color": color, "description": desc})

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self._req("POST", "/issues", json={"title": title, "body": body, "labels": labels})

    def comment(self, number: int, body: str) -> dict:
        return self._req("POST", f"/issues/{number}/comments", json={"body": body})


def issue_title(profile: Profile, j: dict) -> str:
    return f"[L3] {profile.id}: {j['series']} {j['month']}, LLM says {j['category']} (C={j['consistency']:.2f})"


def issue_body(profile: Profile, aid: str, j: dict, dashboard_url: str) -> str:
    runs = "\n".join(
        f"| {i + 1} | {r['category']} | {r['confidence']:.2f} | "
        f"{r['reasoning'].replace('|', '/').replace(chr(10), ' ')} |"
        for i, r in enumerate(j["runs"])
    )
    if j["review_level"] == "mandatory":
        why = ("**Mandatory review**: the LLM labelled this a data-quality event (or could not answer). "
               "No corrective action may be taken before a steward decides.")
    else:
        why = (f"**Advisory review**: the LLM runs disagree (consistency {j['consistency']:.2f} "
               f"< {config.ADVISORY_CONSISTENCY}).")
    categories = "\n".join(f"- `{config.STEWARD_LABEL_PREFIX}{c}`: {d}" for c, d in profile.categories.items())
    return f"""{MARKER.format(f"{profile.id}/{aid}")}
## Anomaly `{aid}` in profile `{profile.id}`

{why}

| | |
|---|---|
| Profile | {profile['title']} |
| Series | `{j['series']}`: {profile.series[j['series']]['description']} |
| Month | {j['month']} |
| Ensemble | {j['votes']} of 4 detectors, score {j['ensemble_score']:.2f} |
| Near a sustained level shift (Page-Hinkley) | {'yes' if j['near_drift'] else 'no'} |
| LLM | `{j['model']}` (T={j['temperature']}), majority **{j['category']}**, consistency {j['consistency']:.2f} |

### LLM runs
| Run | Category | Confidence | Reasoning |
|---|---|---|---|
{runs}

<details><summary>Evidence given to the LLM</summary>

```
{j['prompt']}
```
</details>

### How to decide
Apply **one** label with your classification, add a comment with the justification, then close the issue:

{categories}

Dashboard: {dashboard_url}
"""


def open_review_issues(profile: Profile, judgments: dict, current_ids: set[str], gh: GitHub,
                       dashboard_url: str, max_new: int = config.MAX_NEW_ISSUES) -> dict:
    """Create issues for anomalies that need review and have none yet."""
    gh.ensure_labels(labels_for(profile))
    existing = {}
    for issue in gh.issues():
        m = MARKER_RE.search(issue.get("body") or "")
        if m:
            existing[m.group(1)] = issue["number"]
    notified = notify_rejudgments(profile, judgments, existing, gh)
    todo = sorted(
        (aid for aid, j in judgments.items()
         if aid in current_ids and j["review_level"] != "none" and f"{profile.id}/{aid}" not in existing),
        key=lambda aid: judgments[aid]["month"],
        reverse=True,
    )
    todo.sort(key=lambda aid: judgments[aid]["review_level"] != "mandatory")  # mandatory first
    created = []
    for aid in todo[:max_new]:
        j = judgments[aid]
        labels = [config.ISSUE_LABEL, f"profile:{profile.id}", f"review:{j['review_level']}"]
        if j["category"] in profile.categories:
            labels.append(f"llm:{j['category']}")
        issue = gh.create_issue(issue_title(profile, j), issue_body(profile, aid, j, dashboard_url), labels)
        created.append({"anomaly_id": aid, "issue": issue["number"], "review_level": j["review_level"],
                        "raw": issue})
        time.sleep(1.5)  # stay clear of GitHub's secondary rate limit on content creation
    return {"created": created, "remaining": max(0, len(todo) - max_new), "notified_rejudged": notified}


def notify_rejudgments(profile: Profile, judgments: dict, existing: dict[str, int], gh: GitHub) -> list[str]:
    """Comment on an existing issue when its anomaly was judged again.

    That happens when the anomaly's own data changed (e.g. a retroactive
    correction in the portal) or when the model or prompt version changed.
    The issue is never duplicated; the steward sees the new judgment in the
    same thread and can revise the decision. `issue_notified_judged_at`
    makes this idempotent.
    """
    notified = []
    for aid, j in judgments.items():
        number = existing.get(f"{profile.id}/{aid}")
        if not number or not j.get("rejudge_reason") or j.get("issue_notified_judged_at") == j["judged_at"]:
            continue
        before = j.get("history", [{}])[-1]
        gh.comment(number, (
            f"**This anomaly was judged again** ({j['rejudge_reason']}, {j['judged_at']}).\n\n"
            f"- Before: **{before.get('category')}** (consistency {before.get('consistency')}, "
            f"{before.get('model')} / prompt {before.get('prompt_version')})\n"
            f"- Now: **{j['category']}** (consistency {j['consistency']:.2f}, "
            f"{j['model']} / prompt {j['prompt_version']})\n\n"
            "If you already decided this issue, please check whether the decision still holds."
        ))
        j["issue_notified_judged_at"] = j["judged_at"]
        notified.append(aid)
    return notified


def parse_review(issue: dict, categories: dict) -> dict | None:
    """Read one issue; returns None when it carries no anomaly marker."""
    m = MARKER_RE.search(issue.get("body") or "")
    if not m or "/" not in m.group(1):
        return None
    profile_id, aid = m.group(1).split("/", 1)
    names = [lbl["name"] for lbl in issue.get("labels", [])]
    decisions = [n[len(config.STEWARD_LABEL_PREFIX):] for n in names if n.startswith(config.STEWARD_LABEL_PREFIX)]
    decisions = [d for d in decisions if d in categories]
    if len(decisions) > 1:
        status = "conflicting_labels"
    elif len(decisions) == 1 and issue["state"] == "closed":
        status = "decided"
    else:
        status = "pending"
    return {
        "profile": profile_id,
        "anomaly_id": aid,
        "issue": issue["number"],
        "url": issue["html_url"],
        "state": issue["state"],
        "status": status,
        "steward_category": decisions[0] if status == "decided" else None,
        "review_level": next((n.split(":", 1)[1] for n in names if n.startswith("review:")), None),
        "closed_at": issue.get("closed_at"),
        "updated_at": issue.get("updated_at"),
    }


def sync_reviews(profile: Profile, gh: GitHub, issues: list[dict] | None = None) -> dict:
    reviews = {}
    for issue in issues if issues is not None else gh.issues():
        r = parse_review(issue, profile.categories)
        if r and r["profile"] == profile.id:
            reviews[r["anomaly_id"]] = r
    save_reviews(reviews, profile.paths.reviews)
    return reviews


def load_reviews(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_reviews(reviews: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(reviews.items())), ensure_ascii=False, indent=1), encoding="utf-8")
