"""5L-TEP Layer 3 (Anomaly Detection) pipeline.

Stages, each a sub-command so GitHub Actions can run them as separate steps:

  detect        download the resource, build the monthly series, run the ensemble
                (--from-series: re-run on the committed series, no download)
  judge         LLM-as-a-Judge (Ollama) on anomalies not judged yet
  issues        open GitHub Issues for anomalies that need a steward
  sync-reviews  read steward decisions back from the issues
  report        Layer 3 summary + dashboard data
  run           detect + judge + report (local convenience)
  check-profile validate a profile against the live portal before its first run
  suggest-events LLM suggestions for the event calendar, grounded on Wikipedia (for review)
  list-profiles

Examples:
  python main.py detect --profile ibama-autos-infracao
  python main.py judge --max-judgments 5
  python main.py check-profile profiles/my-portal.json
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import aggregate, config, detectors, judge, report, review
from src import profile as profiles
from src.ckan_source import download, resolve_resource

logger = logging.getLogger("layer3")


def _set_output(name: str, value) -> None:
    """Expose a value to later GitHub Actions steps."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def _load_detections(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"month": str})
    df.index = pd.PeriodIndex(df.pop("month"), freq="M")
    return df


def _log_run(p: profiles.Profile, stage: str, info: dict) -> None:
    p.paths.run_log.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage": stage,
             "run_id": os.environ.get("GITHUB_RUN_ID", "local"), **info}
    with open(p.paths.run_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def cmd_detect(args) -> None:
    p = profiles.load(args.profile)
    if args.from_series:
        # Replication path: the portal file changes daily, but the monthly
        # series of every past run is versioned, so detection can be re-run
        # on exactly the data a given commit analysed.
        monthly = aggregate.load_series(p.paths.series)
        logger.info("Re-running detection on the committed series (%d months)", len(monthly))
    else:
        monthly = _build_series(p, args)
    det, drift = detectors.detect_all(monthly, list(p.series))
    p.paths.results_dir.mkdir(parents=True, exist_ok=True)
    det.to_csv(p.paths.detections)
    report.write_json(p.paths.drift, drift)
    flagged = int(det["anomaly"].sum())
    logger.info("%s: %d months, %d anomalies flagged", p.id, len(monthly), flagged)
    _log_run(p, "detect", {"months": len(monthly), "flagged": flagged, "from_series": bool(args.from_series)})
    _set_output("flagged", flagged)


def _build_series(p: profiles.Profile, args) -> pd.DataFrame:
    src = p["source"]
    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC").tz_localize(None)
    manifest = {"profile": p.id,
                "profile_sha256": hashlib.sha256(p.path.read_bytes()).hexdigest(),
                "as_of": as_of.isoformat()}
    with tempfile.TemporaryDirectory() as tmp:  # raw data never touches the repository
        if args.input:
            raw = Path(args.input)
            manifest.update({"resource_url": f"local file {raw.name}",
                             "checksum_sha256": hashlib.sha256(raw.read_bytes()).hexdigest()})
        else:
            manifest.update(resolve_resource(src["portal_url"], src["dataset_id"], src["resource_name"],
                                             src.get("resource_format", "CSV")))
            raw = Path(tmp) / "resource"
            manifest.update(download(manifest["resource_url"], raw))
        records = aggregate.load_records(raw, p)
        monthly, stats = aggregate.monthly_series(records, p, as_of)
        del records
    manifest["aggregation"] = stats
    monthly = aggregate.analysis_window(monthly, p)
    manifest["analysis_period"] = [str(monthly.index.min()), str(monthly.index.max())]
    aggregate.save_series(monthly, p.paths.series)
    report.write_json(p.paths.manifest, manifest)
    return monthly


def cmd_judge(args) -> None:
    p = profiles.load(args.profile)
    monthly = aggregate.load_series(p.paths.series)
    det = _load_detections(p.paths.detections)
    client = judge.OllamaClient(model=args.model or config.LLM_MODEL)
    res = judge.judge_pending(p, monthly, det, client, args.max_judgments, args.max_minutes)
    logger.info("Judged %d of %d pending anomalies", res["judged_now"], res["pending_before"])
    _log_run(p, "judge", res)
    _set_output("judged_now", res["judged_now"])
    _set_output("pending_after", res["pending_before"] - res["judged_now"])


def cmd_issues(args) -> None:
    p = profiles.load(args.profile)
    gh = review.GitHub.from_env()
    det = _load_detections(p.paths.detections)
    flagged = det[det["anomaly"]]
    current = {judge.anomaly_id(s, m) for m, s in zip(flagged.index, flagged["series"])}
    judgments = judge.load_judgments(p.paths.judgments)
    owner, name = gh.repo.split("/")
    url = f"https://{owner}.github.io/{name}/?profile={p.id}"
    res = review.open_review_issues(p, judgments, current, gh, url, args.max_new)
    if res["notified_rejudged"]:
        judge.save_judgments(judgments, p.paths.judgments)
    # The issue listing can lag a few seconds behind creation; add what was just created.
    issues = gh.issues()
    listed = {i["number"] for i in issues}
    issues += [c["raw"] for c in res["created"] if c["issue"] not in listed]
    review.sync_reviews(p, gh, issues)
    for c in res["created"]:
        c.pop("raw", None)
    mandatory = sum(1 for c in res["created"] if c["review_level"] == "mandatory")
    logger.info("Opened %d issues (%d mandatory), %d still to open",
                len(res["created"]), mandatory, res["remaining"])
    _log_run(p, "issues", res)
    _set_output("new_mandatory", mandatory)
    _set_output("new_issues", len(res["created"]))
    _set_output("issues_remaining", res["remaining"])


def cmd_sync_reviews(args) -> None:
    gh = review.GitHub.from_env()
    issues = gh.issues()
    targets = profiles.available() if args.all else [profiles.load(args.profile)]
    for p in targets:
        reviews = review.sync_reviews(p, gh, issues)
        logger.info("%s: %d reviews synced", p.id, len(reviews))


def cmd_report(args) -> None:
    p = profiles.load(args.profile)
    monthly = aggregate.load_series(p.paths.series)
    det = _load_detections(p.paths.detections)
    drift = json.loads(p.paths.drift.read_text(encoding="utf-8"))
    judgments = judge.load_judgments(p.paths.judgments)
    reviews = review.load_reviews(p.paths.reviews)
    manifest = json.loads(p.paths.manifest.read_text(encoding="utf-8"))
    summary = report.build_summary(p, monthly, det, drift, judgments, reviews, manifest)
    report.write_json(p.paths.summary, summary)
    report.write_json(p.paths.dashboard, report.dashboard_data(p, monthly, det, drift, judgments, reviews, summary))
    report.write_index(profiles.available(), config.ROOT / "docs" / "data" / "index.json")
    l3 = summary["layer3"]
    logger.info("%s: l3_rate=%s l3_pass=%s", p.id, l3["l3_rate"], l3["l3_pass"])
    _set_output("l3_pass", str(l3["l3_pass"]).lower())


def cmd_run(args) -> None:
    cmd_detect(args)
    if not args.skip_llm:
        cmd_judge(args)
    cmd_report(args)


def cmd_check_profile(args) -> None:
    """Validate the profile and read the resource header from the live portal."""
    p = profiles.load(args.profile)
    print(f"Profile {p.id!r} is valid: {len(p.series)} series, {len(p.categories)} categories, "
          f"{len(p.events())} events.")
    src = p["source"]
    res = resolve_resource(src["portal_url"], src["dataset_id"], src["resource_name"],
                           src.get("resource_format", "CSV"))
    print(f"Resource found: {res['resource_url']}")
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "resource"
        meta = download(res["resource_url"], raw)
        print(f"Downloaded {meta['size_bytes'] / 1e6:.1f} MB, sha256 {meta['checksum_sha256'][:16]}...")
        records = aggregate.load_records(raw, p)
    print(f"Read {len(records):,} rows with columns {aggregate.needed_columns(p)}")
    monthly, stats = aggregate.monthly_series(records, p, pd.Timestamp.now())
    window = aggregate.analysis_window(monthly, p)
    print(f"Aggregation: {json.dumps(stats)}")
    print(f"Analysis window: {window.index.min()} to {window.index.max()} ({len(window)} months). Ready.")


def cmd_suggest_events(args) -> None:
    from src import events_suggest

    p = profiles.load(args.profile)
    if not p.get("events_file"):
        raise SystemExit(f"Profile {p.id} has no events_file to write suggestions to")
    det = _load_detections(p.paths.detections)
    years = [int(y) for y in args.years.split(",")] if args.years else None
    client = judge.OllamaClient(model=args.model or config.LLM_MODEL)
    res = events_suggest.suggest(p, det, client, online=not args.offline, years=years, max_years=args.max_years)
    for e in res["added"]:
        logger.info("suggested %s %-9s %s", e["month"], e["kind"], e["label"])
    for d in res["dropped"]:
        logger.info("dropped   %s: %s (%s)", d["year"], d["label"], d["reason"])
    logger.info("%d suggestions added to %s for review", len(res["added"]), p["events_file"])
    _log_run(p, "suggest-events", {"years": res["years"], "added": len(res["added"]),
                                   "dropped": len(res["dropped"]), "online": not args.offline})
    _set_output("added", len(res["added"]))
    _set_output("profile", p.id)


def cmd_list_profiles(args) -> None:
    for p in profiles.available():
        flag = "scheduled" if p.get("scheduled") else "on demand"
        print(f"{p.id:45s} {flag:10s} {p['title']}")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--profile", default=config.DEFAULT_PROFILE, help="profile id or path to a profile JSON")
        sp.set_defaults(fn=fn)
        return sp

    for sp in (add("detect", cmd_detect, "download, aggregate and detect"),
               add("run", cmd_run, "detect + judge + report")):
        sp.add_argument("--input", help="use a local copy of the resource instead of downloading it")
        sp.add_argument("--as-of", help="reference date (YYYY-MM-DD); months from it on are ignored")
        sp.add_argument("--from-series", action="store_true",
                        help="skip the download and re-run detection on the committed monthly series")
    for sp in (add("judge", cmd_judge, "LLM-as-a-Judge on pending anomalies"), sub.choices["run"]):
        sp.add_argument("--model", default=None)
        sp.add_argument("--max-judgments", type=int, default=config.MAX_JUDGMENTS)
        sp.add_argument("--max-minutes", type=float, default=config.MAX_JUDGE_MINUTES)
    sub.choices["run"].add_argument("--skip-llm", action="store_true")
    add("issues", cmd_issues, "open review issues").add_argument(
        "--max-new", type=int, default=config.MAX_NEW_ISSUES)
    add("sync-reviews", cmd_sync_reviews, "read steward decisions").add_argument(
        "--all", action="store_true", help="every profile in profiles/")
    add("report", cmd_report, "summary + dashboard data")
    add("check-profile", cmd_check_profile, "validate a profile against the live portal")
    sp = add("suggest-events", cmd_suggest_events, "LLM suggestions for the event calendar (for review)")
    sp.add_argument("--offline", action="store_true", help="no online source: the model answers from memory")
    sp.add_argument("--years", help="comma-separated years (default: years with anomalies, most recent first)")
    sp.add_argument("--max-years", type=int, default=8)
    sp.add_argument("--model", default=None)
    sub.add_parser("list-profiles", help="list available profiles").set_defaults(fn=cmd_list_profiles)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
