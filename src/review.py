"""Human-in-the-loop review through GitHub Issues.

Two kinds of issues:

- Anomaly issues, one per judged anomaly that needs a steward (mandatory: DQE
  or invalid answers; advisory: label consistency below the threshold).
- Level-shift issues, one per sustained level shift (Page-Hinkley alarm) with
  flagged months around it. The 5L-TEP paper routes confirmed drift to a review
  of the data's structure whatever its cause; the steward answers that question
  once per shift, and the decision applies to every month of the group that has
  no anomaly issue of its own (an anomaly issue always prevails).

The steward decides by applying exactly one `steward:<CATEGORY>` label and
closing the issue; GitHub keeps who did what and when. `sync_reviews` reads
those decisions back into results/<profile>/reviews.json. Hidden markers in
the bodies make everything idempotent: re-running never duplicates an issue.
Issues that no longer need review after a policy change are closed with the
label `superseded` and a pointer to the issue that replaces them.
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

from src import config
from src.profile import Profile

logger = logging.getLogger(__name__)

API = "https://api.github.com"
MARKER = "<!-- l3-anomaly-id: {} -->"
MARKER_RE = re.compile(r"<!-- l3-anomaly-id: (\S+) -->")
DRIFT_MARKER = "<!-- l3-drift-id: {} -->"
DRIFT_RE = re.compile(r"<!-- l3-drift-id: (\S+) -->")
MEMBERS_MARKER = "<!-- l3-drift-members: {} -->"
MEMBERS_RE = re.compile(r"<!-- l3-drift-members: (\S*) -->")
SUPERSEDED = "superseded"


def labels_for(profile: Profile) -> dict[str, tuple[str, str]]:
    labels = {
        config.ISSUE_LABEL: ("5319e7", "5L-TEP Layer 3 anomaly review"),
        f"profile:{profile.id}": ("bfd4f2", profile["title"][:100]),
        "review:mandatory": ("d73a4a", "Steward review required before any action"),
        "review:advisory": ("fbca04", "Low LLM label consistency; review recommended"),
        "review:level-shift": ("f9d0c4", "Sustained level shift: review the cause once for all its months"),
        SUPERSEDED: ("cfd3d7", "Replaced by another issue after a change of review policy"),
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

    def close_superseded(self, number: int, comment: str) -> None:
        self.comment(number, comment)
        self._req("POST", f"/issues/{number}/labels", json={"labels": [SUPERSEDED]})
        self._req("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "not_planned"})


# --- level-shift groups -------------------------------------------------------

def drift_groups(detections: pd.DataFrame, drift: dict) -> dict[str, dict]:
    """Flagged months around each Page-Hinkley alarm, per series.

    A month belongs to the first alarm whose span [onset - tol, alarm + tol]
    contains it; alarms with no flagged month are ignored.
    """
    tol = config.DRIFT_TOLERANCE_MONTHS
    groups, taken = {}, set()
    flagged = detections[detections["anomaly"]]
    for series, points in drift.items():
        months = sorted(m for m in flagged[flagged["series"] == series].index)
        for p in points:
            lo = pd.Period(p["month"], freq="M") - tol
            hi = pd.Period(p["alarm_month"], freq="M") + tol
            members = [f"{series}:{m}" for m in months if lo <= m <= hi and f"{series}:{m}" not in taken]
            if members:
                taken.update(members)
                groups[f"{series}:{p['month']}"] = {"series": series, "onset": p["month"], "alarm": p["alarm_month"],
                                                   "direction": p["direction"], "members": members}
    return groups


def drift_title(profile: Profile, gid: str, g: dict) -> str:
    return (f"[L3] {profile.id}: level shift in {g['series']} around {g['onset']} "
            f"({len(g['members'])} anomalous month{'s' if len(g['members']) > 1 else ''})")


def drift_body(profile: Profile, gid: str, g: dict, judgments: dict, dashboard_url: str) -> str:
    rows = []
    for aid in g["members"]:
        j = judgments.get(aid)
        if j:
            reason = next((r["reasoning"] for r in j["runs"] if r["category"] == j["category"]), "")
            reason = reason.replace("|", "/").replace("\n", " ")[:300]
            rows.append(f"| {j['month']} | **{j['category']}** | {j['consistency']:.2f} | {reason} |")
        else:
            rows.append(f"| {aid.split(':', 1)[1]} | not judged yet | | |")
    categories = "\n".join(f"- `{config.STEWARD_LABEL_PREFIX}{c}`: {d}" for c, d in profile.categories.items())
    return f"""{DRIFT_MARKER.format(f"{profile.id}/{gid}")}
{MEMBERS_MARKER.format(",".join(g['members']))}
## Sustained level shift in `{g['series']}` ({g['direction']}), onset around {g['onset']}

A Page-Hinkley test found a persistent change of level (alarm in {g['alarm']}). Following the 5L-TEP
framework, a confirmed drift calls for a **review of the data's structure, whatever its cause**: was
it a real change (new law, restructuring, change in enforcement) or a change in how the data were
produced (new information system, migration or digitisation of records, change of criteria)?

Series: `{g['series']}`, {profile.series[g['series']]['description']}.

### Anomalous months around the shift, as judged by the LLM
| Month | LLM label | Consistency | Reasoning (majority run) |
|---|---|---|---|
{chr(10).join(rows)}

### How to decide
Apply **one** label with the cause of the shift, comment the justification (and the source, if any),
then close the issue. The decision applies to all the months above that have no issue of their own:

{categories}

Dashboard: {dashboard_url}
"""


# --- anomaly issues ---------------------------------------------------------------

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


def existing_markers(issues: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    anomalies, shifts = {}, {}
    for issue in issues:
        body = issue.get("body") or ""
        if m := MARKER_RE.search(body):
            anomalies[m.group(1)] = issue
        if m := DRIFT_RE.search(body):
            shifts[m.group(1)] = issue
    return anomalies, shifts


def open_review_issues(profile: Profile, judgments: dict, current_ids: set[str], gh: GitHub,
                       dashboard_url: str, max_new: int = config.MAX_NEW_ISSUES,
                       groups: dict[str, dict] | None = None) -> dict:
    """Create the missing anomaly and level-shift issues; close issues that no longer need review."""
    gh.ensure_labels(labels_for(profile))
    anomaly_issues, shift_issues = existing_markers(gh.issues())
    existing = {k: v["number"] for k, v in anomaly_issues.items()}
    notified = notify_rejudgments(profile, judgments, existing, gh)
    groups = groups or {}

    todo = sorted(
        (aid for aid, j in judgments.items()
         if aid in current_ids and j["review_level"] != "none" and f"{profile.id}/{aid}" not in existing),
        key=lambda aid: judgments[aid]["month"],
        reverse=True,
    )
    todo.sort(key=lambda aid: judgments[aid]["review_level"] != "mandatory")  # mandatory first
    shifts_todo = [gid for gid, g in sorted(groups.items(), key=lambda kv: kv[1]["onset"], reverse=True)
                   if f"{profile.id}/{gid}" not in shift_issues and any(a in judgments for a in g["members"])]
    created, shifts_created = [], []
    for aid in todo[:max_new]:
        j = judgments[aid]
        labels = [config.ISSUE_LABEL, f"profile:{profile.id}", f"review:{j['review_level']}"]
        if j["category"] in profile.categories:
            labels.append(f"llm:{j['category']}")
        issue = gh.create_issue(issue_title(profile, j), issue_body(profile, aid, j, dashboard_url), labels)
        created.append({"anomaly_id": aid, "issue": issue["number"], "review_level": j["review_level"],
                        "raw": issue})
        time.sleep(1.5)  # stay clear of GitHub's secondary rate limit on content creation
    for gid in shifts_todo[: max(0, max_new - len(created))]:
        g = groups[gid]
        issue = gh.create_issue(drift_title(profile, gid, g), drift_body(profile, gid, g, judgments, dashboard_url),
                                [config.ISSUE_LABEL, f"profile:{profile.id}", "review:level-shift"])
        shift_issues[f"{profile.id}/{gid}"] = issue
        shifts_created.append({"group": gid, "issue": issue["number"], "raw": issue})
        time.sleep(1.5)
    superseded = close_obsolete(profile, judgments, anomaly_issues, shift_issues, groups, gh)
    remaining = max(0, len(todo) - max_new) + max(0, len(shifts_todo) - max(0, max_new - len(created)))
    return {"created": created, "shifts_created": shifts_created, "superseded": superseded,
            "remaining": remaining, "notified_rejudged": notified}


def close_obsolete(profile: Profile, judgments: dict, anomaly_issues: dict, shift_issues: dict,
                   groups: dict, gh: GitHub) -> list[int]:
    """Close open anomaly issues that no longer need review and have no steward decision yet."""
    group_of = {aid: gid for gid, g in groups.items() for aid in g["members"]}
    closed = []
    for key, issue in anomaly_issues.items():
        profile_id, aid = key.split("/", 1)
        if profile_id != profile.id or issue["state"] != "open":
            continue
        names = {lbl["name"] for lbl in issue.get("labels", [])}
        if any(n.startswith(config.STEWARD_LABEL_PREFIX) for n in names):
            continue  # a steward already started deciding: leave it alone
        j = judgments.get(aid)
        if not j or j["review_level"] != "none":
            continue
        gid = group_of.get(aid)
        shift = shift_issues.get(f"{profile.id}/{gid}") if gid else None
        where = f"the level-shift issue #{shift['number']}" if shift else "no issue (it no longer needs review)"
        gh.close_superseded(issue["number"], (
            "Closed after a change of review policy: months next to a sustained level shift are now reviewed "
            f"together, once per shift. This month is covered by {where}."))
        closed.append(issue["number"])
        time.sleep(1.0)
    return closed


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


# --- reading decisions back ---------------------------------------------------------

def _decision(issue: dict, categories: dict) -> tuple[str, str | None, list[str]]:
    names = [lbl["name"] for lbl in issue.get("labels", [])]
    decisions = [n[len(config.STEWARD_LABEL_PREFIX):] for n in names if n.startswith(config.STEWARD_LABEL_PREFIX)]
    decisions = [d for d in decisions if d in categories]
    if len(decisions) > 1:
        status = "conflicting_labels"
    elif len(decisions) == 1 and issue["state"] == "closed":
        status = "decided"
    else:
        status = "pending"
    return status, decisions[0] if status == "decided" else None, names


def parse_review(issue: dict, categories: dict) -> dict | None:
    """Read one anomaly issue; None for other issues and for superseded ones."""
    m = MARKER_RE.search(issue.get("body") or "")
    if not m or "/" not in m.group(1):
        return None
    status, category, names = _decision(issue, categories)
    if SUPERSEDED in names:
        return None
    profile_id, aid = m.group(1).split("/", 1)
    return {
        "profile": profile_id,
        "anomaly_id": aid,
        "issue": issue["number"],
        "url": issue["html_url"],
        "state": issue["state"],
        "status": status,
        "steward_category": category,
        "review_level": next((n.split(":", 1)[1] for n in names if n.startswith("review:")), None),
        "closed_at": issue.get("closed_at"),
        "updated_at": issue.get("updated_at"),
    }


def parse_shift(issue: dict, categories: dict) -> dict | None:
    """Read one level-shift issue: its decision and the anomalies it covers."""
    body = issue.get("body") or ""
    m = DRIFT_RE.search(body)
    if not m or "/" not in m.group(1):
        return None
    status, category, _ = _decision(issue, categories)
    members = MEMBERS_RE.search(body)
    profile_id, gid = m.group(1).split("/", 1)
    return {"profile": profile_id, "group": gid, "issue": issue["number"], "url": issue["html_url"],
            "state": issue["state"], "status": status, "steward_category": category,
            "members": [x for x in (members.group(1).split(",") if members else []) if x],
            "closed_at": issue.get("closed_at"), "updated_at": issue.get("updated_at")}


def sync_reviews(profile: Profile, gh: GitHub, issues: list[dict] | None = None) -> dict:
    """reviews.json: one entry per anomaly; its own issue prevails over its level-shift issue."""
    issues = issues if issues is not None else gh.issues()
    reviews = {}
    for issue in issues:
        r = parse_review(issue, profile.categories)
        if r and r["profile"] == profile.id:
            reviews[r["anomaly_id"]] = r
    for issue in issues:
        s = parse_shift(issue, profile.categories)
        if not s or s["profile"] != profile.id:
            continue
        for aid in s["members"]:
            if aid not in reviews:
                reviews[aid] = {"profile": profile.id, "anomaly_id": aid, "issue": s["issue"], "url": s["url"],
                                "state": s["state"], "status": s["status"],
                                "steward_category": s["steward_category"], "review_level": "level-shift",
                                "via_level_shift": s["group"], "closed_at": s["closed_at"],
                                "updated_at": s["updated_at"]}
    save_reviews(reviews, profile.paths.reviews)
    return reviews


def load_reviews(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_reviews(reviews: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(reviews.items())), ensure_ascii=False, indent=1), encoding="utf-8")
