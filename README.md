# 5LTEP-L3 · ANEEL instance (control experiment)

[![Tests](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/tests.yml/badge.svg)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/tests.yml) [![Layer 3](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Flsp3cesarschool%2F5ltep-layer3-aneel%2Fmain%2Fdocs%2Fdata%2Fstatus-aneel-autos-infracao.json)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/layer3.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**English** · [Português](LEIAME.md)

**5L-TEP Layer 3 anomaly detection applied to the infraction notices of ANEEL, Brazil's electricity
regulator: a second instance of [5ltep-layer3](https://github.com/lsp3cesarschool/5ltep-layer3), set up by the author as a control case for
the IBAMA study.**

| Resource | What you find there |
|---|---|
| 📊 **Dashboard** | [lsp3cesarschool.github.io/5ltep-layer3-aneel](https://lsp3cesarschool.github.io/5ltep-layer3-aneel/?lang=en): anomalies, LLM labels, steward decisions and the provenance of every result |
| 🧑‍⚖️ **Review queue** | [![open reviews](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/layer3?label=open%20reviews&color=0366d6)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Alayer3) [![pending](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/review%3Apending?label=pending&color=d73a4a)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Areview%3Apending) [![advisory](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/review%3Aadvisory?label=advisory&color=fbca04)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Areview%3Aadvisory) [![level shift](https://img.shields.io/github/issues/lsp3cesarschool/5ltep-layer3-aneel/review%3Alevel-shift?label=level%20shift&color=f9d0c4)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Areview%3Alevel-shift)<br>live counts; each badge opens its list of issues |
| 🏛️ **Main instance** | [5ltep-layer3](https://github.com/lsp3cesarschool/5ltep-layer3): IBAMA, and the full documentation |
| 🧪 **Model choice** | [5ltep-layer3-modeltest](https://github.com/lsp3cesarschool/5ltep-layer3-modeltest): the monthly benchmark that picks the LLM judge |
| 🔒 **Security** | [SECURITY.md](SECURITY.md): what is not trusted (the model, the data portal, web sources), how the toolkit contains it, and how to report a vulnerability |

> **Status: research demonstration.** This repository is not operated by, affiliated with or endorsed
> by ANEEL; it only reads ANEEL's open data. It shows that the toolkit can be reused on another portal.
> It does not assume that ANEEL will review its results or adopt it. The open review issues demonstrate
> the flow: no steward is assigned.

## Use case in one paragraph

ANEEL publishes every infraction notice issued to electricity companies (generation, transmission,
distribution) by its own inspection areas and by the state agencies that inspect on its behalf.
Suppose the regulator, or anyone who reuses these data, wants to know whether the published record is
trustworthy and where to look first if something is wrong. This layer builds monthly series (number
of notices, total value of penalties), finds the months that depart from the usual pattern, and uses a
local AI model to check which departures have a known explanation (a new regulation, a recurring
inspection cycle) and which look like a **data problem** (a month with no records in an active series,
a batch of notices entered at once). The unexplained ones go to a person first; the AI only proposes,
and a data steward confirms or corrects every decision that leads to action.

## Why a control experiment

The Layer 3 toolkit of the Five-Layer Trust Engineering Pyramid (5L-TEP) was built on IBAMA's open
data. A method that works on one dataset may only have learned that dataset's quirks. This repository
runs **the same code** on a different agency, portal and scale, following the steps another
institution would take to adopt it, and asks two questions:

1. **Reuse (the *R* of FAIR):** can the toolkit be adopted by writing a profile, with no code changes?
2. **Transfer:** do detection, the LLM-as-a-Judge and the review protocol behave the same way on a
   small, sparse dataset as on IBAMA's large one?

What differs from the main repository is only:

| File | Why |
|---|---|
| [`profiles/aneel-autos-infracao.json`](profiles/aneel-autos-infracao.json) | the dataset: portal, resource, columns, series, domain text for the LLM |
| [`profiles/events/brazil-electricity-regulation.json`](profiles/events/brazil-electricity-regulation.json) | the event calendar, started almost empty and meant to be filled with *Suggest events* and checked by a steward |
| this README and its Portuguese version, [`LEIAME.md`](LEIAME.md) | |

The IBAMA profiles and results are not included. Everything else (detectors, LLM-as-a-Judge,
human-in-the-loop review, dashboard, workflows, tests) is identical to
[`5ltep-layer3@1554bc4`](https://github.com/lsp3cesarschool/5ltep-layer3/tree/1554bc497d64e5d49eb3e6fa1ea775a6134713a8),
and the built instance passes the same test suite before every update.

## Key terms

| Term | Meaning here |
|---|---|
| **Anomaly** | a month of a monthly series (number of notices, total of penalties) that departs from its usual pattern, flagged by at least 2 of 4 statistical detectors |
| **Level shift** | a lasting change of level (not a one-month spike), detected by a Page-Hinkley test |
| **LLM-as-a-Judge** | a small language model, run locally and free of charge, that reads each anomaly with its context and says which of the four causes below explains it best |
| **Data steward** | the person who confirms or corrects the judge's label (through a GitHub Issue) before any action |

The four causes (categories) the judge chooses from:

| Code | Category | Example (ANEEL) | What it means |
|---|---|---|---|
| **PDC** | Policy-Driven Change | notices change after a new normative resolution or a change of government | explained by a known event: document it |
| **SP** | Seasonal Pattern | an inspection cycle that repeats in the same months every year | expected behaviour: no action |
| **DQE** | Data-Quality Event | a month with no notices in an otherwise active series; hundreds of notices entered in one month | a **data problem**: always reviewed by a steward |
| **GES** | Genuine Enforcement Shift | a lasting change in inspection intensity with no event and no data signs | a real change nobody has explained yet |

## How ANEEL's data differ from IBAMA's

| | IBAMA (main study) | ANEEL (control) |
|---|---|---|
| Records | ~711,000 notices since 1977 | ~1,600 notices since 2018 |
| Resource | zip with one CSV per year | one CSV |
| Date / key / value columns | `DAT_HORA_AUTO_INFRACAO` / `SEQ_AUTO_INFRACAO` / `VAL_AUTO_INFRACAO` | `DatLavraturaAutoInfracao` / `NumAutoInfracao` / `VlrPenalidade` |
| Cancellation flag | yes (excluded, counted) | none |
| Monthly volume | hundreds to thousands | usually under 20, with empty months |
| Currency | several currencies before 1994 (converted to Reais) | Reais only |
| Event calendar | curated, ~14 verified events | 3 verified events, to be extended |
| Licence of the data | IBAMA open data | ODbL |

## How it works

The pipeline is the one documented in the [main README](https://github.com/lsp3cesarschool/5ltep-layer3#readme);
in short:

```
┌────────────────────────────────────────────────────────────┐
│  GitHub Actions: monthly cron + "Run workflow" button      │
│  (public repo runner: 4 vCPU / 16 GB, free of charge)      │
└─────────────────────────────┬──────────────────────────────┘
                              ▼
 ① Source     CKAN API of dadosabertos.aneel.gov.br → CSV (SHA-256 recorded)
 ② Aggregate  only date, identifier and penalty columns (no company names or CNPJ kept)
 ③ Detect     Z-score · MAD · Isolation Forest · LSTM-ED (vote ≥ 2) + Page-Hinkley
 ④ Judge      Ollama + the model approved by the benchmark, 3 seeded runs, JSON answer
 ⑤ Review     GitHub Issues: steward:<CATEGORY> label + close (review:pending for DQE)
 ⑥ Report     layer3_summary.json (l3_rate, l3_pass, anomaly_flags) + dashboard
                              ▼
       Git history of every series, detection, judgment and review
```

- **Batches:** each run judges up to 25 anomalies, commits, and starts the next batch until nothing is
  pending; a month is plenty of time for the whole history.
- **No re-judging by default:** each judgment stores a fingerprint of its own data and the model and
  prompt version that produced it. It is judged again only if its data change, or if a steward asks
  (workflow input `rejudge` = `stale` or `all`, or the **Re-judge** button of the dashboard).
- **Model:** `LLM_MODEL=auto` (default) uses the model the
  [benchmark](https://github.com/lsp3cesarschool/5ltep-layer3-modeltest) currently approves; a
  repository variable can pin another one.
- **Review:** DQE labels are always sent to a steward; inconsistent labels (the three runs disagree)
  are advised; each sustained level shift becomes one issue for all the months around it.
- **Event calendar:** *Suggest events* asks the LLM for events grounded on the Wikipedia pages
  "*year* no Brasil" and opens a pull request; suggestions are marked `suggested` until a steward
  verifies them.

## First results (30/09/2026)

*A snapshot for the record; the dashboard always shows the current state.*

**Data.** 1,601 rows read; 11 duplicated notice numbers dropped; 18 notices without a penalty value;
analysis window 2018-06 to 2026-08 (99 months). One decision date has the year "0209", a typing error
of the kind Layers 1-2 should catch.

**Detection.** 10 anomalous months (4 in the number of notices, 6 in the total of penalties), no
sustained level shift. A spike stands out: 455 notices in December 2024 against a usual median of
about 6, most likely notices entered in a batch.

**How sensitive detection is here.** The synthetic injection benchmark of
[`evaluation/`](evaluation/) injects anomalies of known type (×3 spikes, drops, two-month gaps, level
shifts) into the real series. On ANEEL the ensemble found 7% of them in the number of notices and 26%
in the penalties (IBAMA's number of notices: 80%). With a median of ~6 notices a month and empty
months, a threefold change stays within the normal variation: Layer 3 is much less sensitive on small,
sparse series, and this has to be reported per series.

**Judge.** The same 10 anomalies were judged by two models:

| | gemma3:4b (first model) | qwen3:4b (benchmark's choice since 30/09/2026) |
|---|---|---|
| Labels | SP 6 · GES 2 · DQE 2 | DQE 7 · GES 3 |
| Agreement between the two | 2 of 10 anomalies | |

qwen3:4b, which scored best on the benchmark's gold set, reads months with zero penalties as "near
zero in an active series" (a data-quality sign) and flags them as DQE; gemma3:4b called most of them
seasonal. On a series where empty months are normal, neither reading is obviously right: this is
exactly the kind of decision the design leaves to a steward, and it shows that the benchmark's gold set, built
on IBAMA's large series, does not yet represent low-volume data.

## What the control experiment showed

- **Reuse without code changes: yes, after two fixes.** Only the profile, the calendar and this README
  were written. Running it exposed two assumptions that held for IBAMA but not in general, both fixed
  in the shared code of the main repository: (1) sparse months only at the start of a series (the
  original rule discarded 93 of ANEEL's 99 months); (2) a default profile hard-coded to IBAMA.
- **Detection transfers poorly to small series:** see above.
- **The judge's labels depend on the model more on sparse data:** 2 of 10 agreements between two
  models, against a much more stable picture on IBAMA's January drops.
- **Same cost:** zero, on the same free runners.

## Running it, and adapting it again

| Workflow | When | What |
|---|---|---|
| `layer3.yml` | 5th of every month, and manual (dashboard *Run Layer 3 now*, *Re-judge*) | detect → judge in batches → review issues → report |
| `reviews.yml` | when a `layer3` issue is labelled or closed | records steward decisions, refreshes the dashboard |
| `events.yml` | manual (dashboard *Suggest events*) | LLM event suggestions → pull request |
| `model-check.yml` | 22nd of every month | only if the model is pinned: proposes the benchmark's choice |
| `tests.yml` | push / pull request | test suite |

This instance is itself the recipe for a third one: fork the main repository, replace the profiles
with your own (`python main.py check-profile profiles/<yours>.json` validates one against the live
portal), mark it `"scheduled": true`, delete `data/`, `results/` and `docs/data/`, enable Actions and
Pages, and run the workflow once. The main README details each step and every profile field.

## Reproducibility

Every run records the SHA-256 of the file analysed and of the profile, every method parameter, the
Python and package versions, and for each judgment the full prompt, the three answers with their seeds,
the model digest and the prompt version. The monthly series are versioned, so detection can be re-run
on exactly the data of any past commit with `python main.py detect --from-series`, even though the
portal's file changes over time.

## Limitations

- Small dataset: 99 months and 10 anomalies are too few for statistics on the judge's quality.
- The event calendar is nearly empty: most anomalies are judged without the context a regulation
  expert would bring.
- Detection sensitivity is low on this series (see *First results*).
- No steward decisions, by design: the review flow is working and ready to be adopted, and the
  review metrics (human-LLM agreement, review time) fill in automatically if and when a steward uses
  it. The author does not act as a steward, which would be self-evaluation.

## Documentation and references

Method, parameters, human-in-the-loop protocol, FAIR and replicability notes, and how to adapt the
toolkit: **<https://github.com/lsp3cesarschool/5ltep-layer3#readme>**. Model choice:
**<https://github.com/lsp3cesarschool/5ltep-layer3-modeltest>**.

- Pinheiro, L. S., et al. (2026). *Towards Trust Engineering in Open Data Systems: A Layered Conceptual Framework Integrating Quality Assurance and Governance Perspectives*. SOFTENG 2026, IARIA, pp. 21–28.
- ANEEL. *Auto de Infração*. Portal de Dados Abertos da ANEEL. <https://dadosabertos.aneel.gov.br/dataset/auto-de-infracao>

## License

Code: MIT, see [LICENSE](LICENSE). The monthly series in `data/` are aggregates derived from ANEEL's
open data (ODbL); when reusing them, cite ANEEL's open data portal as the original source.
