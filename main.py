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

from src import aggregate, config, detectors, judge, report, review, safety, translate
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


def _model() -> str:
    """The model of this run (resolves LLM_MODEL=auto through the model benchmark)."""
    if config.LLM_MODEL == "auto":
        from src import model_select
        sel = model_select.resolve()
        logger.info("Model: %s (from %s)", sel["model"], sel["source"])
    return config.LLM_MODEL


def cmd_resolve_model(args) -> None:
    """Resolve LLM_MODEL=auto once per job and export it to the later steps."""
    from src import model_select
    sel = model_select.resolve()
    print(json.dumps(sel))
    env = os.environ.get("GITHUB_ENV")
    if env:
        values = {"LLM_MODEL": sel["model"], "LLM_THINK": sel["think"], "LLM_MODEL_SOURCE": sel["source"],
                  "LLM_DIGEST": (sel.get("digest") or "").removeprefix("sha256:")}
        # These end up in shell commands of later steps: refuse anything unexpected.
        if not (safety.valid_model(values["LLM_MODEL"]) and values["LLM_THINK"] in safety.THINK_VALUES
                and values["LLM_MODEL_SOURCE"] in ("pinned", "benchmark", "fallback")
                and safety.valid_digest(values["LLM_DIGEST"])):
            sys.exit(f"Refusing an unexpected model selection: {values}")
        with open(env, "a", encoding="utf-8") as fh:
            for key, value in values.items():
                fh.write(f"{key}={value}\n")
    _set_output("model", sel["model"])


def cmd_judge(args) -> None:
    p = profiles.load(args.profile)
    monthly = aggregate.load_series(p.paths.series)
    det = _load_detections(p.paths.detections)
    client = judge.OllamaClient(model=args.model or _model())
    res = judge.judge_pending(p, monthly, det, client, args.max_judgments, args.max_minutes,
                              rejudge=args.rejudge, rejudge_before=args.rejudge_before or None)
    logger.info("Judged %d of %d pending anomalies (model %s, rejudge=%s)", res["judged_now"],
                res["pending_before"], client.model, args.rejudge)
    _log_run(p, "judge", res)
    _set_output("judged_now", res["judged_now"])
    _set_output("pending_after", res["pending_before"] - res["judged_now"])


def cmd_accept_artifact(args) -> None:
    """Validate the files the analysis job handed over and copy them into the repository.

    The analysis job runs the model with a read-only token; this one writes to the repository
    and never runs the model. Only this profile's data and results are accepted, with the
    expected structure and bounded sizes (src/safety.py)."""
    p = profiles.load(args.profile)
    src = Path(args.dir)
    accepted = safety.accept_artifact(src, config.ROOT, p.id, set(p.categories))
    chain = safety.read_chain(src)
    logger.info("Accepted %d files from the analysis job: %s", len(accepted), ", ".join(accepted))
    _set_output("pending_after", chain["pending_after"])
    _set_output("rejudge_before", chain["rejudge_before"])


def cmd_accept_events(args) -> None:
    """Check the calendar written by the suggestion job (which runs the model, read-only) and,
    if it only appends suggestions, write it into the repository for the pull request."""
    p = profiles.load(args.profile)
    target = config.ROOT / p["events_file"]
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"events": []}
    new = json.loads(Path(args.file).read_text(encoding="utf-8"))
    added = safety.check_events_update(old, new)
    target.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        lines = [f"- `{e['month']}` ({e['kind']}): {safety.safe_markdown(e['label'], 300)}" for e in added]
        Path(args.summary).write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("%d suggestions accepted for %s", len(added), p["events_file"])
    _set_output("added", len(added))
    _set_output("events_file", p["events_file"])


def cmd_translate(args) -> None:
    """Machine-translate the dashboard texts that have no Portuguese version yet."""
    p = profiles.load(args.profile)
    judgments = judge.load_judgments(p.paths.judgments)
    store = translate.load(p.paths.translations)
    client = judge.OllamaClient(model=args.model or _model())
    systems = {lang: translate.system_prompt(p, lang) for lang in translate.LANGS}
    manual = {lang: translate.profile_i18n(p, lang).get("texts", {}) for lang in translate.LANGS}
    res = translate.translate_pending(translate.dashboard_texts(p, judgments), store, client,
                                      p.paths.translations, args.max_minutes, systems, manual)
    logger.info("Translated %d texts (%d failed, %d left for the next run)", res["translated"],
                res["failed"], res["remaining"])
    _log_run(p, "translate", res)


def cmd_issues(args) -> None:
    p = profiles.load(args.profile)
    gh = review.GitHub.from_env()
    det = _load_detections(p.paths.detections)
    flagged = det[det["anomaly"]]
    current = {judge.anomaly_id(s, m) for m, s in zip(flagged.index, flagged["series"])}
    judgments = judge.load_judgments(p.paths.judgments)
    policy_changes = judge.apply_review_policy(judgments)
    owner, name = gh.repo.split("/")
    url = f"https://{owner}.github.io/{name}/?profile={p.id}&lang=en"  # issues are written in English
    drift = json.loads(p.paths.drift.read_text(encoding="utf-8")) if p.paths.drift.exists() else {}
    groups = review.drift_groups(det, drift)
    res = review.open_review_issues(p, judgments, current, gh, url, args.max_new, groups)
    if res["notified_rejudged"] or policy_changes:
        judge.save_judgments(judgments, p.paths.judgments)
    # The issue listing can lag a few seconds behind creation; add what was just created.
    issues = gh.issues()
    listed = {i["number"] for i in issues}
    issues += [c["raw"] for c in res["created"] + res["shifts_created"] if c["issue"] not in listed]
    review.sync_reviews(p, gh, issues)
    for c in res["created"] + res["shifts_created"]:
        c.pop("raw", None)
    pending = sum(1 for c in res["created"] if c["review_level"] == "pending")
    logger.info("Opened %d anomaly issues (%d pending) and %d level-shift issues; closed %d superseded; "
                "%d still to open", len(res["created"]), pending, len(res["shifts_created"]),
                len(res["superseded"]), res["remaining"])
    _log_run(p, "issues", res)
    _set_output("new_pending", pending)
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
    _model()  # the summary names the model in use
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
    continues = {"yes": True, "no": False}.get(getattr(args, "chain_continues", "no" if getattr(args, "skip_llm", False) else "auto"))
    state, info = report.status_from_summary(summary, continues)
    report.write_status(p.id, state, **info)
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
    client = judge.OllamaClient(model=args.model or _model())
    res = events_suggest.suggest(p, det, client, online=not args.offline, years=years, max_years=args.max_years,
                                 minutes=args.minutes)
    for e in res["added"]:
        logger.info("suggested %s %-9s %s", e["month"], e["kind"], e["label"])
    for d in res["dropped"]:
        logger.info("dropped   %s: %s (%s)", d["year"], d["label"], d["reason"])
    logger.info("%d suggestions added to %s for review", len(res["added"]), p["events_file"])
    _log_run(p, "suggest-events", {"years": res["years"], "remaining_years": res["remaining_years"],
                                   "added": len(res["added"]),
                                   "dropped": len(res["dropped"]), "online": not args.offline})
    _set_output("added", len(res["added"]))
    _set_output("profile", p.id)
    if res["remaining_years"]:
        print(f"::warning::Time budget reached; years not asked yet (run again with them): "
              f"{','.join(map(str, res['remaining_years']))}")


def cmd_check_model(args) -> None:
    from src import model_check

    if config.LLM_MODEL == "auto":
        logger.info("LLM_MODEL=auto: the model benchmark's choice is followed automatically; nothing to propose")
        return

    if args.dry_run:
        rec = model_check.fetch()
        print(json.dumps(model_check.decide(rec, config.LLM_MODEL), indent=1))
        return
    res = model_check.run(review.GitHub.from_env())
    logger.info("check-model: %s", res)


def cmd_status(args) -> None:
    """Mark the status badge as running (start of a chain) or interrupted (failed/cancelled run)."""
    p = profiles.load(args.profile)
    report.write_status(p.id, args.state)


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
        sp.add_argument("--rejudge", choices=judge.REJUDGE_MODES, default="none",
                        help="none: only new anomalies or changed data; stale: also what another model or "
                             "prompt version judged; all: everything judged before --rejudge-before")
        sp.add_argument("--rejudge-before", default="", help="ISO timestamp (start of the chain of batches)")
    sub.choices["run"].add_argument("--skip-llm", action="store_true")
    add("issues", cmd_issues, "open review issues").add_argument(
        "--max-new", type=int, default=config.MAX_NEW_ISSUES)
    add("sync-reviews", cmd_sync_reviews, "read steward decisions").add_argument(
        "--all", action="store_true", help="every profile in profiles/")
    sp = add("translate", cmd_translate, "machine-translate the dashboard texts into Portuguese")
    sp.add_argument("--model", default=None)
    sp.add_argument("--max-minutes", type=float, default=config.TRANSLATE_MAX_MINUTES)
    add("report", cmd_report, "summary + dashboard data").add_argument(
        "--chain-continues", choices=["auto", "yes", "no"], default="auto",
        help="for the status badge: whether another batch follows (auto: while anomalies await judgment)")
    add("status", cmd_status, "set the status badge").add_argument(
        "--state", choices=["running", "interrupted"], required=True)
    add("accept-artifact", cmd_accept_artifact, "validate and apply the analysis job's results").add_argument(
        "--dir", required=True, help="folder where the analysis job's artifact was downloaded")
    sp = add("accept-events", cmd_accept_events, "validate the event suggestions before the pull request")
    sp.add_argument("--file", required=True, help="calendar written by the suggestion job")
    sp.add_argument("--summary", help="write a safe Markdown list of the suggestions here")
    add("check-profile", cmd_check_profile, "validate a profile against the live portal")
    sp = add("suggest-events", cmd_suggest_events, "LLM suggestions for the event calendar (for review)")
    sp.add_argument("--offline", action="store_true", help="no online source: the model answers from memory")
    sp.add_argument("--years", help="comma-separated years (default: years with anomalies, most recent first)")
    sp.add_argument("--max-years", type=int, default=0, help="at most this many years (default: all)")
    sp.add_argument("--minutes", type=float, default=None, help="time budget (default SUGGEST_MAX_MINUTES)")
    sp.add_argument("--model", default=None)
    sub.add_parser("list-profiles", help="list available profiles").set_defaults(fn=cmd_list_profiles)
    sub.add_parser("resolve-model", help="resolve LLM_MODEL=auto through the model benchmark").set_defaults(
        fn=cmd_resolve_model)
    cm = sub.add_parser("check-model", help="compare LLM_MODEL with the model benchmark's recommendation")
    cm.add_argument("--dry-run", action="store_true", help="only print the decision")
    cm.set_defaults(fn=cmd_check_model)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
