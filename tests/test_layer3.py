"""Unit and integration tests. No network access and no real LLM: the CKAN
resource is a synthetic zip and Ollama is replaced by a fake client."""

import copy
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from src import aggregate, config, detectors, judge, report, review
from src import profile as profiles
from src.profile import Paths, Profile

BASE_PROFILE = {
    "id": "test-profile",
    "title": "Synthetic notices",
    "source": {"portal_url": "https://example.org", "dataset_id": "d", "resource_name": "r"},
    "file": {"compression": "zip", "member_pattern": "*.csv", "sep": ";", "encoding": "utf-8"},
    "columns": {"date": "DATA", "key": "ID"},
    "exclude": {"column": "CANCELADO", "equals": "S", "label": "cancelled", "description": "cancelled notices"},
    "filters": [],
    "sparse_min_records": 3,
    "series": [
        {"name": "notices", "kind": "count", "description": "Notices per month"},
        {"name": "fines", "kind": "sum", "column": "VALOR", "number_format": "br", "description": "Fines"},
    ],
    "domain": "Synthetic domain.",
    "record_label": "notices",
    "categories": {"PDC": "Policy", "SP": "Seasonal", "DQE": "Data quality", "GES": "Genuine shift"},
}


def make_profile(tmp_path, **overrides) -> Profile:
    raw = copy.deepcopy(BASE_PROFILE)
    raw.update(overrides)
    p = Profile(raw)
    p.paths = Paths.for_profile(p.id, tmp_path)
    return p


def write_zip(path, rows_by_file: dict[str, list[str]]):
    header = "ID;DATA;VALOR;CANCELADO;UF;NOME_INFRATOR;CPF_CNPJ_INFRATOR"
    with zipfile.ZipFile(path, "w") as zf:
        for name, rows in rows_by_file.items():
            zf.writestr(name, "\n".join([header, *rows]) + "\n")
    return path


def synthetic_rows(months: int = 60, per_month: int = 10, start: str = "2020-01") -> list[str]:
    rows, seq = [], 0
    for i, month in enumerate(pd.period_range(start, periods=months, freq="M")):
        for d in range(per_month):
            seq += 1
            rows.append(f"{seq};{month.start_time.date()} 10:00:00;1.000,50;N;PA;Fulano {seq};000.000.000-{seq % 100:02d}")
    return rows


# --- profiles ----------------------------------------------------------------

def test_shipped_profiles_are_valid():
    """Whatever profiles an instance ships (IBAMA here, others in forks) must load."""
    ps = profiles.available()
    assert ps
    assert profiles.default_id() in {p.id for p in ps}
    for p in ps:
        assert p.paths.series.name == "monthly_series.csv"
        for ev in p.events():
            pd.Period(ev["month"], freq="M")
            assert ev["source"] and ev["status"] in ("verified", "suggested")


@pytest.mark.parametrize("breakage", [
    {"series": [{"name": "x", "kind": "median", "description": ""}]},
    {"series": [{"name": "x", "kind": "sum", "description": ""}]},
    {"columns": {"key": "ID"}},
    {"filters": [{"column": "UF"}]},
    {"categories": {"INVALID": "reserved"}},
])
def test_invalid_profiles_are_rejected(breakage):
    raw = copy.deepcopy(BASE_PROFILE)
    raw.update(breakage)
    with pytest.raises(ValueError):
        Profile(raw)


# --- aggregation -------------------------------------------------------------

def test_parse_number_br_and_plain():
    s = pd.Series(["1.234,56", "1500,00", "", None, "abc", "12.5"])
    br = aggregate.parse_number(s, "br")
    assert br.iloc[0] == pytest.approx(1234.56)
    assert br.iloc[1] == 1500.0
    assert br.iloc[2:5].isna().all()
    assert aggregate.parse_number(pd.Series(["12.5"]), "plain").iloc[0] == 12.5


def test_monthly_series_counts_excludes_and_drops_current_month(tmp_path):
    p = make_profile(tmp_path)
    rows = [
        "1;2024-01-05;100,00;N;PA;A;1",
        "2;2024-01-20;50,50;S;PA;B;2",       # cancelled: excluded
        ";2024-01-21;10,00;N;PA;C;3",         # no key: counted, flagged
        "3;2024-03-02;1.000,00;N;SP;D;4",
        "3;2024-03-02;1.000,00;N;SP;D;4",     # duplicate key: dropped
        "4;2024-04-10;5,00;N;SP;E;5",         # current month: dropped
    ]
    zp = write_zip(tmp_path / "r.zip", {"a_2024.csv": rows})
    monthly, stats = aggregate.monthly_series(aggregate.load_records(zp, p), p, pd.Timestamp("2024-04-15"))
    assert list(monthly.index.astype(str)) == ["2024-01", "2024-02", "2024-03"]
    assert monthly.loc["2024-01", "notices"] == 2
    assert monthly.loc["2024-01", "fines"] == pytest.approx(110.0)
    assert monthly.loc["2024-01", "excluded"] == 1
    assert monthly.loc["2024-01", "missing_key"] == 1
    assert monthly.loc["2024-02", "notices"] == 0
    assert monthly.loc["2024-03", "fines"] == 1000.0
    assert stats["rows_duplicate_key_dropped"] == 1
    assert stats["rows_missing_key"] == 1


def test_personal_data_never_read_nor_saved(tmp_path):
    p = make_profile(tmp_path)
    zp = write_zip(tmp_path / "r.zip", {"a.csv": synthetic_rows(40)})
    records = aggregate.load_records(zp, p)
    assert "NOME_INFRATOR" not in records.columns and "CPF_CNPJ_INFRATOR" not in records.columns
    monthly, _ = aggregate.monthly_series(records, p, pd.Timestamp("2030-01-01"))
    aggregate.save_series(monthly, p.paths.series)
    text = p.paths.series.read_text()
    assert "Fulano" not in text and "000.000.000" not in text


def test_filters_define_a_data_cut(tmp_path):
    p = make_profile(tmp_path, filters=[{"column": "UF", "in": ["SP"]}])
    rows = ["1;2024-01-05;1,00;N;PA;A;1", "2;2024-01-06;1,00;N;SP;B;2", "3;2024-02-06;1,00;N;SP;C;3"]
    zp = write_zip(tmp_path / "r.zip", {"a.csv": rows})
    monthly, stats = aggregate.monthly_series(aggregate.load_records(zp, p), p, pd.Timestamp("2024-03-15"))
    assert stats["rows_after_filters"] == 2
    assert monthly["notices"].tolist() == [1, 1]


def test_analysis_window_drops_sparse_start_and_applies_period(tmp_path):
    p = make_profile(tmp_path)
    idx = pd.period_range("2000-01", periods=60, freq="M")
    counts = [0] * 10 + [10] * 50
    counts[40] = 0  # a quiet month later on is data, not a sparse start
    monthly = pd.DataFrame({"notices": counts, "fines": 1.0, "excluded": 0, "missing_key": 0}, index=idx)
    window = aggregate.analysis_window(monthly, p)
    assert window.index.min() == pd.Period("2000-05", freq="M")  # first 12 months with median >= 3
    assert pd.Period("2003-05", freq="M") in window.index
    p2 = make_profile(tmp_path, period={"start": "2001-01", "end": None})
    assert aggregate.analysis_window(monthly, p2).index.min() == pd.Period("2001-01", freq="M")
    with pytest.raises(ValueError):
        aggregate.analysis_window(monthly.iloc[:30], p)


def test_plain_csv_resource(tmp_path):
    p = make_profile(tmp_path, file={"compression": "none", "sep": ";", "encoding": "utf-8"})
    csv = tmp_path / "r.csv"
    csv.write_text("ID;DATA;VALOR;CANCELADO;UF\n1;2024-01-05;2,00;N;PA\n", encoding="utf-8")
    assert len(aggregate.load_records(csv, p)) == 1


# --- detectors ---------------------------------------------------------------

def seasonal_series(n=180, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    values = 1000 * (1 + 0.1 * np.sin(2 * np.pi * t / 12)) * rng.lognormal(0, 0.03, n)
    return pd.Series(values, index=pd.period_range("2005-01", periods=n, freq="M"))


def test_point_spike_is_flagged_by_ensemble():
    s = seasonal_series()
    s.iloc[120] *= 6
    det, _ = detectors.run_detectors(s)
    assert det["anomaly"].iloc[120]
    assert det["votes"].iloc[120] >= 3
    assert det["anomaly"].sum() <= 0.1 * len(s)


def test_detectors_are_deterministic():
    s = seasonal_series()
    s.iloc[100] *= 0.2
    a, _ = detectors.run_detectors(s)
    b, _ = detectors.run_detectors(s)
    pd.testing.assert_frame_equal(a, b)


def test_page_hinkley_finds_level_shift_but_not_noise():
    s = seasonal_series(seed=3)
    x = np.log1p(s.to_numpy())
    assert detectors.page_hinkley(x, config.PH_DELTA, config.PH_LAMBDA) == []
    x_shift = x.copy()
    x_shift[90:] += np.log(5)
    points = detectors.page_hinkley(x_shift, config.PH_DELTA, config.PH_LAMBDA)
    assert any(90 <= p["alarm_index"] <= 92 and p["index"] <= 90 and p["direction"] == "up" for p in points)


def test_lstm_scores_spike_highest():
    pytest.importorskip("torch")
    s = seasonal_series()
    s.iloc[130] *= 8
    err, thr = detectors.lstm_autoencoder(np.log1p(s.to_numpy()), 12, 16, 0.2, 30, 99.0, 42)
    assert int(np.argmax(err)) in range(128, 133)
    assert err[130] > thr


# --- LLM-as-a-Judge ----------------------------------------------------------

class FakeClient:
    model = config.LLM_MODEL

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def info(self):
        return {"model": self.model, "model_digest": "sha256:fake", "ollama_version": "0.0-test"}

    def generate(self, system, prompt, seed, schema, temperature=None, num_ctx=None):
        self.prompts.append((system, prompt, seed, schema))
        return self.answers.pop(0), 0.1


def answer(cat, conf=0.8):
    return json.dumps({"reasoning": f"because {cat}", "category": cat, "confidence": conf})


def test_parse_response_rejects_unknown_labels():
    cats = BASE_PROFILE["categories"]
    assert judge.parse_response(answer("SP"), cats)["category"] == "SP"
    assert judge.parse_response(answer("XYZ"), cats)["category"] == "INVALID"
    assert judge.parse_response("not json", cats)["category"] == "INVALID"


def test_majority_consistency_and_review_levels():
    runs = [{"category": c, "confidence": 0.5} for c in ("GES", "GES", "SP")]
    assert judge.aggregate_runs(runs) == {"category": "GES", "consistency": 0.667}
    split = [{"category": "PDC", "confidence": 0.9}, {"category": "SP", "confidence": 0.4},
             {"category": "GES", "confidence": 0.5}]
    assert judge.aggregate_runs(split) == {"category": "PDC", "consistency": 0.333}
    assert judge.review_level("DQE", 1.0) == "mandatory"
    assert judge.review_level("PDC", 0.333) == "advisory"
    assert judge.review_level("GES", 0.667) == "none"
    # drift is reviewed once per level shift (review.drift_groups), not per anomaly
    assert judge.review_level("GES", 1.0, near_drift=True) == "none"
    js = {"a": {"category": "GES", "consistency": 1.0, "near_drift": True, "review_level": "advisory"},
          "b": {"category": "SP", "consistency": 0.33, "near_drift": False, "review_level": "none"}}
    assert judge.apply_review_policy(js) == 2
    assert js["a"]["review_level"] == "none" and js["b"]["review_level"] == "advisory"


def test_level_shift_groups_issue_and_decision_for_all_months(tmp_path, monkeypatch):
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    p = make_profile(tmp_path)
    idx = pd.period_range("1995-06", periods=14, freq="M")
    det = pd.DataFrame({"series": "notices", "anomaly": False}, index=idx)
    for m in ("1996-01", "1996-02", "1996-03", "1996-07"):
        det.loc[pd.Period(m, freq="M"), "anomaly"] = True
    drift = {"notices": [{"month": "1996-01", "alarm_month": "1996-03", "direction": "up"}]}
    groups = review.drift_groups(det, drift)
    assert list(groups) == ["notices:1996-01"]
    assert groups["notices:1996-01"]["members"] == ["notices:1996-01", "notices:1996-02", "notices:1996-03"]

    base = {"series": "notices", "consistency": 1.0, "votes": 2, "ensemble_score": 0.6, "near_drift": True,
            "model": "m", "temperature": 0.7, "prompt": "e", "runs": [{"category": "GES", "confidence": .9,
                                                                        "reasoning": "r"}]}
    judgments = {f"notices:{m}": {**base, "month": m, "category": "GES", "review_level": "none"}
                 for m in ("1996-01", "1996-02", "1996-03")}
    judgments["notices:1996-02"].update(category="DQE", review_level="mandatory")
    # an old advisory issue for 1996-01, opened by the previous per-month drift policy
    gh = FakeGitHub()
    gh.created.append({"title": "old", "body": review.MARKER.format("test-profile/notices:1996-01"), "labels": []})
    closed = []
    gh.close_superseded = lambda number, comment: closed.append((number, comment))
    res = review.open_review_issues(p, judgments, set(judgments), gh, "https://x", groups=groups)
    assert [c["anomaly_id"] for c in res["created"]] == ["notices:1996-02"]  # the mandatory one stays individual
    assert [s["group"] for s in res["shifts_created"]] == ["notices:1996-01"]
    assert closed and closed[0][0] == 1 and "#3" in closed[0][1]  # old issue points to the level-shift issue
    again = review.open_review_issues(p, judgments, set(judgments), gh, "https://x", groups=groups)
    assert again["created"] == [] and again["shifts_created"] == []

    shift_issue = {**gh.created[2], "number": 3, "html_url": "u3", "state": "closed",
                   "labels": [{"name": "layer3"}, {"name": "steward:DQE"}]}
    own_issue = {**gh.created[1], "number": 2, "html_url": "u2", "state": "closed",
                 "labels": [{"name": "layer3"}, {"name": "steward:SP"}]}
    old = {**gh.created[0], "number": 1, "html_url": "u1", "state": "closed",
           "labels": [{"name": "layer3"}, {"name": "superseded"}]}
    reviews = review.sync_reviews(p, gh, [old, own_issue, shift_issue])
    assert reviews["notices:1996-01"]["steward_category"] == "DQE"   # via the level-shift issue
    assert reviews["notices:1996-02"]["steward_category"] == "SP"    # its own issue prevails
    assert reviews["notices:1996-03"]["via_level_shift"] == "notices:1996-01"


def pipeline_inputs(tmp_path):
    p = make_profile(tmp_path)
    s = seasonal_series()
    s.iloc[-3] *= 6
    monthly = pd.DataFrame({"notices": s.round(), "fines": s * 100, "excluded": 1, "missing_key": 0})
    det, drift = detectors.detect_all(monthly, list(p.series))
    return p, monthly, det, drift


def test_judge_caches_and_respects_budget(tmp_path):
    p, monthly, det, _ = pipeline_inputs(tmp_path)
    n_flagged = int(det["anomaly"].sum())
    assert n_flagged >= 2
    client = FakeClient([answer("DQE")] * 3 + [answer("SP"), answer("SP"), answer("GES")] * 50)
    res = judge.judge_pending(p, monthly, det, client, max_judgments=1)
    assert res["judged_now"] == 1
    saved = judge.load_judgments(p.paths.judgments)
    (entry,) = saved.values()
    assert entry["category"] == "DQE" and entry["review_level"] == "mandatory"
    assert entry["month"] == str(det[det["anomaly"]].index.max())  # most recent first
    assert entry["model_digest"] == "sha256:fake"
    system, prompt, seed, schema = client.prompts[0]
    assert "Synthetic domain." in system and "<== anomaly" in prompt
    assert schema["properties"]["category"]["enum"] == list(BASE_PROFILE["categories"])
    assert [x[2] for x in client.prompts] == config.LLM_SEEDS[:3]
    res2 = judge.judge_pending(p, monthly, det, client, max_judgments=100)
    assert res2["pending_before"] == n_flagged - 1
    assert len(judge.load_judgments(p.paths.judgments)) == n_flagged


def test_same_data_is_never_judged_again_changed_data_is(tmp_path):
    p, monthly, det, _ = pipeline_inputs(tmp_path)
    n = int(det["anomaly"].sum())
    client = FakeClient([answer("SP")] * 3 * n + [answer("DQE")] * 3 * n)
    judge.judge_pending(p, monthly, det, client, max_judgments=100)
    assert len(client.prompts) == 3 * n
    # New months arrive: every judged anomaly keeps its own data -> no new calls.
    later = pd.concat([monthly, monthly.iloc[-6:].set_axis(monthly.index[-6:] + 6)])
    det_later = det.copy()
    res = judge.judge_pending(p, later, det_later, client, max_judgments=100)
    assert res["pending_before"] == 0 and len(client.prompts) == 3 * n
    # A retroactive correction in an anomalous month -> judged again are exactly the
    # anomalies whose own data (that month and the 12 before) include it.
    flagged = det[det["anomaly"]]
    month = flagged.index.min()
    series = flagged.loc[[month], "series"].iloc[0]
    changed = later.copy()
    changed.loc[month, series] *= 1.5
    affected = sum(1 for m in flagged.index if 0 <= (m - month).n <= 12)
    res = judge.judge_pending(p, changed, det_later, client, max_judgments=100)
    assert res["pending_before"] == affected >= 1
    entry = judge.load_judgments(p.paths.judgments)[judge.anomaly_id(series, month)]
    assert entry["category"] == "DQE" and entry["rejudge_reason"] == "data changed"
    assert entry["history"][-1]["category"] == "SP"


def test_model_or_prompt_change_does_not_rejudge_unless_asked(tmp_path, monkeypatch):
    p, monthly, det, _ = pipeline_inputs(tmp_path)
    n = int(det["anomaly"].sum())
    client = FakeClient([answer("SP")] * 3 * n + [answer("GES")] * 3 * n)
    judge.judge_pending(p, monthly, det, client, max_judgments=100)
    # a new model (or prompt version) keeps the earlier judgments, which record who made them
    client.model = "another-model:4b"
    monkeypatch.setattr(config, "PROMPT_VERSION", "v-next")
    assert judge.judge_pending(p, monthly, det, client, max_judgments=100)["judged_now"] == 0
    # re-judging is explicit: "stale" re-judges what another model/prompt judged, once
    assert judge.judge_pending(p, monthly, det, client, max_judgments=100, rejudge="stale")["judged_now"] == n
    assert judge.judge_pending(p, monthly, det, client, max_judgments=100, rejudge="stale")["judged_now"] == 0
    entry = next(iter(judge.load_judgments(p.paths.judgments).values()))
    assert entry["rejudge_reason"].startswith("re-judged on request") and entry["model"] == "another-model:4b"
    assert entry["history"][-1]["category"] == "SP" and entry["category"] == "GES"


def test_rejudge_all_in_a_chain_never_rejudges_its_own_output(tmp_path):
    p, monthly, det, _ = pipeline_inputs(tmp_path)
    n = int(det["anomaly"].sum())
    client = FakeClient([answer("SP")] * 3 * n * 3)
    judge.judge_pending(p, monthly, det, client, max_judgments=100)
    chain_start = "9999-01-01T00:00:00+00:00"  # everything judged so far is older
    first = judge.judge_pending(p, monthly, det, client, max_judgments=1, rejudge="all", rejudge_before=chain_start)
    assert first["judged_now"] == 1 and first["pending_before"] == n
    before_second = judge.load_judgments(p.paths.judgments)
    newest = max(j["judged_at"] for j in before_second.values())
    second = judge.judge_pending(p, monthly, det, client, max_judgments=100, rejudge="all", rejudge_before=newest)
    assert second["pending_before"] <= n - 1  # the batch's own judgment is not taken again


def test_model_auto_follows_the_benchmark_and_falls_back(monkeypatch):
    from src import model_select

    class Resp:
        def __init__(self, data): self.data = data
        def json(self): return self.data

    monkeypatch.setattr(config, "LLM_MODEL", "auto")
    monkeypatch.setattr(config, "LLM_THINK", "")
    monkeypatch.setattr(model_select.requests, "get", lambda url, timeout: Resp(
        {"use": {"model": "qwen3:4b", "options": {"think": False}}, "generated_at": "t"}))
    assert model_select.resolve() == {"model": "qwen3:4b", "think": "false", "source": "benchmark",
                                      "benchmark_generated_at": "t"}
    assert config.LLM_MODEL == "qwen3:4b"

    def boom(url, timeout):
        raise model_select.requests.ConnectionError("offline")
    monkeypatch.setattr(config, "LLM_MODEL", "auto")
    monkeypatch.setattr(model_select.requests, "get", boom)
    assert model_select.resolve()["source"] == "fallback" and config.LLM_MODEL == config.FALLBACK_MODEL
    monkeypatch.setattr(config, "LLM_MODEL", "gemma3:4b")
    assert model_select.resolve() == {"model": "gemma3:4b", "think": config.LLM_THINK, "source": "pinned"}


def test_legacy_judgments_are_backfilled_not_rejudged(tmp_path):
    p, monthly, det, _ = pipeline_inputs(tmp_path)
    flagged = det[det["anomaly"]]
    legacy = {judge.anomaly_id(s, m): {"model": config.LLM_MODEL, "prompt_version": config.PROMPT_VERSION,
                                       "category": "SP", "consistency": 1.0}
              for m, s in zip(flagged.index, flagged["series"])}
    judge.save_judgments(legacy, p.paths.judgments)
    client = FakeClient([])
    res = judge.judge_pending(p, monthly, det, client)
    assert res["pending_before"] == 0 and client.prompts == []
    assert all("data_fingerprint" in j for j in judge.load_judgments(p.paths.judgments).values())


def test_data_change_comments_existing_issue_once(tmp_path, monkeypatch):
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    p = make_profile(tmp_path)
    j = {"series": "notices", "month": "2020-01", "category": "GES", "consistency": 1.0, "review_level": "mandatory",
         "votes": 2, "ensemble_score": 0.6, "near_drift": False, "model": "m", "temperature": 0.7, "prompt": "e",
         "runs": [], "data_fingerprint": "new", "judged_at": "2026-10-05T06:00:00+00:00",
         "rejudge_reason": "data changed", "prompt_version": "v2",
         "history": [{"category": "DQE", "consistency": 1.0, "model": "m", "prompt_version": "v2"}]}
    judgments = {"notices:2020-01": j}
    gh = FakeGitHub()
    gh.created.append({"title": "t", "body": review.MARKER.format("test-profile/notices:2020-01"), "labels": []})
    comments = []
    gh.comment = lambda number, body: comments.append((number, body))
    review.open_review_issues(p, judgments, set(judgments), gh, "https://x")
    review.open_review_issues(p, judgments, set(judgments), gh, "https://x")
    assert len(comments) == 1 and comments[0][0] == 1 and "DQE" in comments[0][1]
    assert len(gh.created) == 1  # never a duplicate issue


# --- currency reforms and event calendar ---------------------------------------

def test_currency_conversion_and_monetary_events():
    from src import monetary

    reforms = monetary.load("profiles/monetary/brazil-currency.json")
    monetary.validate(reforms)
    f = monetary.conversion_factors(pd.Series(["1994-06-30", "1994-07-01", "1993-07-31", "1986-02-27"]), reforms)
    assert f.tolist() == [2750.0, 1.0, 2750.0 * 1000, 2750.0 * 1000 * 1 * 1000 * 1000]
    evs = monetary.as_events(reforms)
    assert [e["month"] for e in evs] == ["1986-02", "1989-01", "1990-03", "1993-08", "1994-07"]
    assert all(e["kind"] == "monetary" and e["status"] == "verified" for e in evs)


def test_convert_currency_in_aggregation(tmp_path):
    series = copy.deepcopy(BASE_PROFILE["series"])
    series[1]["convert_currency"] = True
    p = make_profile(tmp_path, series=series, monetary_file="profiles/monetary/brazil-currency.json")
    rows = ["1;1994-06-10;2.750.000,00;N;PA", "2;1994-07-10;1.000,00;N;PA"]
    zp = write_zip(tmp_path / "r.zip", {"a.csv": rows})
    monthly, _ = aggregate.monthly_series(aggregate.load_records(zp, p), p, pd.Timestamp("1994-08-15"))
    assert monthly["fines"].tolist() == [pytest.approx(1000.0), pytest.approx(1000.0)]
    with pytest.raises(ValueError):
        make_profile(tmp_path, series=series)  # convert_currency without monetary_file


def test_event_status_filtering(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "ev.json").write_text(json.dumps({"events": [
        {"month": "2020-01", "kind": "policy", "label": "a", "source": "s"},
        {"month": "2020-02", "kind": "policy", "label": "b", "source": "s", "status": "suggested"},
        {"month": "2020-03", "kind": "policy", "label": "c", "source": "s", "status": "rejected"},
        {"month": "2020-04", "kind": "policy", "label": "d", "source": "s", "status": "suggested",
         "origin": "llm-memory"},
        {"month": "2020-05", "kind": "policy", "label": "e", "source": "s", "status": "verified",
         "origin": "llm-memory"},
    ]}), encoding="utf-8")
    p = make_profile(tmp_path, events_file="ev.json")
    assert [e["label"] for e in p.events()] == ["a", "b", "e"]  # ungrounded suggestion "d" never used
    assert [e["label"] for e in p.events(include_suggested=False)] == ["a", "e"]
    near = [{**e, "offset_months": 0} for e in p.events()]
    assert "[unverified suggestion]" in "\n".join(
        f"{e['label']}" + (" [unverified suggestion]" if e["status"] == "suggested" else "") for e in near)


def test_grounding_rejects_invented_evidence():
    from src import events_suggest as es

    source = "25 de janeiro – O rompimento de uma barragem de rejeitos em Brumadinho, Minas Gerais, deixa 270 mortos."
    assert es.grounded("O rompimento de uma barragem de rejeitos em Brumadinho, Minas Gerais", source)
    assert es.grounded("o rompimento de uma BARRAGEM de rejeitos em brumadinho minas gerais", source)
    assert not es.grounded("Nova lei ambiental sancionada pelo presidente em janeiro", source)
    assert not es.grounded("barragem", source)  # too short to count as a quote


def test_suggest_events_appends_grounded_suggestions_only(tmp_path, monkeypatch):
    from src import events_suggest as es

    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "ev.json").write_text(json.dumps({"events": [
        {"month": "2019-01", "kind": "political", "label": "Change of federal administration", "source": "s"},
        {"month": "2019-07", "kind": "policy", "label": "Old rejected thing about decree", "source": "s",
         "status": "rejected"}]}), encoding="utf-8")
    p = make_profile(tmp_path, events_file="ev.json", event_sources={"wikipedia": {"lang": "pt", "title": "{year} no Brasil"}})
    text = ("1 de janeiro – Novo presidente toma posse como presidente do Brasil.\n"
            "25 de janeiro – O rompimento de uma barragem de rejeitos em Brumadinho deixa centenas de mortos.")
    monkeypatch.setattr(es, "fetch_wikipedia", lambda lang, title: (text, "https://pt.wikipedia.org/wiki/2019_no_Brasil"))
    items = {"events": [
        # right quote, wrong month: the source's own date ("25 de janeiro") prevails
        {"month": "2019-03", "kind": "external", "label": "Brumadinho tailings dam collapse", "relevance": "r",
         "relevance_score": 0.9,
         "evidence": "O rompimento de uma barragem de rejeitos em Brumadinho deixa centenas de mortos"},
        {"month": "2019-03", "kind": "policy", "label": "Invented decree", "relevance": "r", "relevance_score": 0.9,
         "evidence": "Decreto inventado que nao aparece no texto da fonte"},
        {"month": "2019-01", "kind": "political", "label": "Change of the federal administration", "relevance": "r",
         "relevance_score": 0.9, "evidence": "Novo presidente toma posse como presidente do Brasil"},
        {"month": "2019-02", "kind": "external", "label": "Football final", "relevance": "r", "relevance_score": 0.2,
         "evidence": "Flamengo vence a final do campeonato estadual no Maracana lotado"},
    ]}
    text += "\n14 de fevereiro – Flamengo vence a final do campeonato estadual no Maracana lotado."
    client = FakeClient([json.dumps(items)])
    idx = pd.PeriodIndex(["2019-01", "2019-02"], freq="M")
    det = pd.DataFrame({"series": "notices", "anomaly": [True, False]}, index=idx)
    res = es.suggest(p, det, client, max_events=4)
    assert [(e["month"], e["label"]) for e in res["added"]] == [("2019-01", "Brumadinho tailings dam collapse")]
    assert res["added"][0]["month_corrected_from"] == "2019-03"
    assert {d["reason"] for d in res["dropped"]} == {
        "evidence not found in the source", "already in the calendar", "relevance 0.20 below 0.6"}
    saved = json.loads((tmp_path / "ev.json").read_text(encoding="utf-8"))["events"]
    new = [e for e in saved if e.get("status") == "suggested"]
    assert len(new) == 1 and new[0]["origin"] == "llm+wikipedia" and "wikipedia" in new[0]["source"]
    assert "Change of federal administration" in client.prompts[0][1]  # known events are shown to the model


def test_month_in_source_reads_the_preceding_date():
    from src import events_suggest as es

    text = "=== Janeiro ===\n25 de janeiro – Barragem rompe em Brumadinho.\n=== Abril ===\n29 de abril – Chuvas fortes no Rio Grande do Sul causam enchentes."
    assert es.month_in_source("Chuvas fortes no Rio Grande do Sul causam enchentes", text) == 4
    assert es.month_in_source("Barragem rompe em Brumadinho", text) == 1
    assert es.month_in_source("frase que nao existe no texto", text) is None


def test_model_check_proposes_only_clear_switches():
    from src import model_check

    rec = {"switch_recommended": True, "reason": "x beats y", "benchmark": "https://b", "gold_cases": 31,
           "recommended": {"model": "qwen3.5:4b", "backend": "ollama", "options": {"think": False},
                           "macro_f1": 0.8, "consistency": 0.9, "latency_p90_s": 40},
           "production": {"model": "gemma3:4b", "macro_f1": 0.6}}
    assert model_check.decide(rec, "gemma3:4b")["action"] == "propose"
    assert model_check.decide(rec, "qwen3.5:4b")["action"] == "none"
    assert model_check.decide({**rec, "switch_recommended": False}, "gemma3:4b")["action"] == "none"
    body = model_check.issue_body(rec, "gemma3:4b")
    assert model_check.MARKER in body and "`LLM_THINK` to `false`" in body and "`qwen3.5:4b`" in body


def test_events_near_window():
    evs = [{"month": "2020-03", "kind": "external", "label": "x", "source": "s"}]
    assert judge.events_near(evs, pd.Period("2020-08", freq="M"), 6)[0]["offset_months"] == -5
    assert judge.events_near(evs, pd.Period("2020-10", freq="M"), 6) == []


# --- human-in-the-loop -------------------------------------------------------

def test_issue_marker_roundtrip_and_steward_decision(tmp_path):
    p = make_profile(tmp_path)
    j = {"series": "notices", "month": "2020-01", "category": "DQE", "consistency": 1.0,
         "review_level": "mandatory", "votes": 3, "ensemble_score": 0.7, "near_drift": False,
         "model": "m", "temperature": 0.7, "prompt": "evidence",
         "runs": [{"category": "DQE", "confidence": 0.9, "reasoning": "a | b"}] * 3}
    body = review.issue_body(p, "notices:2020-01", j, "https://x")
    issue = {"number": 7, "html_url": "u", "state": "closed", "body": body, "closed_at": "t", "updated_at": "t",
             "labels": [{"name": "layer3"}, {"name": "review:mandatory"}, {"name": "steward:SP"}]}
    r = review.parse_review(issue, p.categories)
    assert r["profile"] == "test-profile" and r["anomaly_id"] == "notices:2020-01"
    assert r["status"] == "decided" and r["steward_category"] == "SP"
    issue["state"] = "open"
    assert review.parse_review(issue, p.categories)["status"] == "pending"
    issue["labels"].append({"name": "steward:GES"})
    assert review.parse_review(issue, p.categories)["status"] == "conflicting_labels"


class FakeGitHub:
    repo = "owner/repo"

    def __init__(self):
        self.created, self.labels = [], set()

    def ensure_labels(self, wanted):
        self.labels |= set(wanted)

    def issues(self):
        return [{"number": i + 1, "body": c["body"], "labels": [], "state": "open", "html_url": ""}
                for i, c in enumerate(self.created)]

    def create_issue(self, title, body, labels):
        self.created.append({"title": title, "body": body, "labels": labels})
        return {"number": len(self.created)}


def test_open_review_issues_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(review.time, "sleep", lambda s: None)
    p = make_profile(tmp_path)
    base = {"series": "notices", "consistency": 1.0, "votes": 2, "ensemble_score": 0.6, "near_drift": False,
            "model": "m", "temperature": 0.7, "prompt": "e", "runs": []}
    judgments = {
        "notices:2020-01": {**base, "month": "2020-01", "category": "DQE", "review_level": "mandatory"},
        "notices:2020-02": {**base, "month": "2020-02", "category": "SP", "review_level": "none"},
        "notices:2020-03": {**base, "month": "2020-03", "category": "GES", "review_level": "advisory"},
    }
    gh = FakeGitHub()
    res = review.open_review_issues(p, judgments, set(judgments), gh, "https://x")
    assert [c["anomaly_id"] for c in res["created"]] == ["notices:2020-01", "notices:2020-03"]
    assert "steward:DQE" in gh.labels and "profile:test-profile" in gh.labels
    again = review.open_review_issues(p, judgments, set(judgments), gh, "https://x")
    assert again["created"] == []


# --- Layer 3 summary ---------------------------------------------------------

def test_layer3_score_rules(tmp_path):
    idx = pd.period_range("2024-01", periods=12, freq="M")
    det = pd.DataFrame({"series": "notices", "anomaly": False}, index=idx)
    det.loc[pd.Period("2024-05", freq="M"), "anomaly"] = True
    det.loc[pd.Period("2024-09", freq="M"), "anomaly"] = True
    j = {"model": config.LLM_MODEL, "prompt_version": config.PROMPT_VERSION}
    judgments = {"notices:2024-05": {**j, "category": "SP", "review_level": "none"},
                 "notices:2024-09": {**j, "category": "DQE", "review_level": "mandatory"}}
    s = report.layer3_score(det, judgments, {})
    assert s["pairs_evaluated"] == 12 and s["l3_rate"] == pytest.approx(11 / 12, abs=1e-3) and not s["l3_pass"]
    reviews = {"notices:2024-09": {"status": "decided", "steward_category": "SP"}}
    s2 = report.layer3_score(det, judgments, reviews)
    assert s2["l3_pass"] and s2["l3_rate"] == 1.0
    assert {f["period"] for f in s2["anomaly_flags"]} == {"2024-05", "2024-09"}


def test_end_to_end_without_llm(tmp_path, monkeypatch):
    """detect -> report through main.py on a synthetic zip, all outputs in tmp."""
    import main

    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "profiles").mkdir()
    raw = copy.deepcopy(BASE_PROFILE)
    (tmp_path / "profiles" / "test-profile.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    rows = synthetic_rows(months=72, per_month=20)
    rows += [f"{9000 + i};2024-06-15;10,00;N;PA;X;Y" for i in range(200)]  # spike in 2024-06
    zp = write_zip(tmp_path / "r.zip", {"a.csv": rows})
    main.main(["run", "--profile", str(tmp_path / "profiles" / "test-profile.json"), "--skip-llm",
               "--input", str(zp), "--as-of", "2026-01-15"])
    summary = json.loads((tmp_path / "results" / "test-profile" / "layer3_summary.json").read_text())
    assert summary["anomalies"]["flagged"] >= 1
    assert summary["source"]["aggregation"]["rows_read"] == len(rows)
    assert summary["environment"]["packages"]["pandas"]
    dash = json.loads((tmp_path / "docs" / "data" / "test-profile.json").read_text())
    assert any(a["month"] == "2024-06" and a["series"] == "notices" for a in dash["anomalies"])
    index = json.loads((tmp_path / "docs" / "data" / "index.json").read_text())
    assert index["profiles"] == [{"id": "test-profile", "title": "Synthetic notices"}]
