# 5LTEP-L3 · ANEEL instance

**5L-TEP Layer 3 anomaly detection applied to ANEEL's infraction notices: a second, independent
instance of [5ltep-layer3](https://github.com/lsp3cesarschool/5ltep-layer3).**

[![Tests](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/tests.yml/badge.svg)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/tests.yml)
[![Layer 3](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/layer3.yml/badge.svg)](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/actions/workflows/layer3.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

📊 **Dashboard:** <https://lsp3cesarschool.github.io/5ltep-layer3-aneel/>
🧑‍⚖️ **Review queue:** [open `layer3` issues](https://github.com/lsp3cesarschool/5ltep-layer3-aneel/issues?q=is%3Aissue+is%3Aopen+label%3Alayer3)

## What this repository is

The Layer 3 toolkit of the Five-Layer Trust Engineering Pyramid (5L-TEP) was built on IBAMA's open
data. This repository runs **the same code** on a different agency and portal, the way any other
institution would adopt it: it monitors the infraction notices (*autos de infração*) of ANEEL,
Brazil's electricity regulator, published at
[dadosabertos.aneel.gov.br](https://dadosabertos.aneel.gov.br/dataset/auto-de-infracao).

It serves as a control case for the claim that the toolkit is reusable (the *R* of FAIR): if a
second portal needed code changes, the toolkit would not be generic. What differs from the main
repository is only:

| File | Why |
|---|---|
| [`profiles/aneel-autos-infracao.json`](profiles/aneel-autos-infracao.json) | the dataset: portal, resource, columns, series, domain text for the LLM |
| [`profiles/events/brazil-electricity-regulation.json`](profiles/events/brazil-electricity-regulation.json) | the event calendar, started almost empty and meant to be filled with *Suggest events* |
| this README | |

The IBAMA profiles and results are not included. Everything else (detectors, LLM-as-a-Judge,
human-in-the-loop review, dashboard, workflows, tests) is identical to
[`5ltep-layer3@676383a`](https://github.com/lsp3cesarschool/5ltep-layer3/tree/676383a97f52342d6257fe7c8747c3de0535c339).

Setting it up took the steps of the main README's section *Running your own instance*: write the
profile, check it against the live portal with `python main.py check-profile`, mark it
`"scheduled": true`, enable Actions and Pages, run the workflow once. Doing so exposed two
assumptions that held for IBAMA but not in general (sparse months only at the start of a series; a
hard-coded default profile); both were fixed in the shared code of the main repository.

## How ANEEL's data differ from IBAMA's

| | IBAMA | ANEEL |
|---|---|---|
| Records | ~711,000 notices since 1977 | ~1,600 notices since 2018 |
| Resource | zip with one CSV per year | one CSV |
| Date / key / value columns | `DAT_HORA_AUTO_INFRACAO` / `SEQ_AUTO_INFRACAO` / `VAL_AUTO_INFRACAO` | `DatLavraturaAutoInfracao` / `NumAutoInfracao` / `VlrPenalidade` |
| Cancellation flag | yes (excluded, counted) | none |
| Monthly volume | hundreds to thousands | usually under 20, with empty months |
| Currency | several currencies before 1994 (converted to Reais) | Reais only |

## Documentation

Method, parameters, human-in-the-loop protocol, FAIR and replicability notes, and how to adapt the
toolkit are documented in the main repository:
**<https://github.com/lsp3cesarschool/5ltep-layer3#readme>**.

Results of this instance are versioned here, under `data/aneel-autos-infracao/` and
`results/aneel-autos-infracao/`, and shown on the dashboard.

## License

Code: MIT, see [LICENSE](LICENSE). The monthly series in `data/` are aggregates derived from ANEEL's
open data (ODbL); when reusing them, cite ANEEL's open data portal as the original source.
