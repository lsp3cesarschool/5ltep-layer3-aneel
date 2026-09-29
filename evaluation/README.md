# Evaluation

Every number this repository reports comes from a script here; results are written to
[`results/`](results/). Run from the repository root.

| Script | Needs | Measures |
|---|---|---|
| `synthetic_injection.py` | the committed monthly series (`data/<profile>/monthly_series.csv`); no network, no LLM | Detection with known ground truth: one anomaly at a time (spike, dip, two-month gap, level shift, default magnitude ×3) is injected into the real series at months that are not flagged in the clean series. Recall, precision and induced false alarms per detector and for the ensemble; Page-Hinkley recall on level shifts. |
| `judge_report.py` | `results/<profile>/judgments.json` and `reviews.json` from the Actions runs | LLM-as-a-Judge: category distribution, label consistency (share of the 3 runs agreeing with the majority), unanimous rate, invalid answers, latency per call; human-LLM agreement and confusion matrix over steward decisions. |

```bash
python evaluation/synthetic_injection.py --profile ibama-autos-infracao --trials 20
python evaluation/synthetic_injection.py --profile ibama-autos-infracao --series fine_total_brl --trials 20
python evaluation/judge_report.py --profile ibama-autos-infracao
```

Notes on interpretation:

- *Precision* in the injection benchmark counts, as false positives, only the **new** flags an
  injection causes outside the injected span (and outside the 12 months after it, where rolling
  baselines legitimately react). Flags already present in the clean series are real-data anomalies,
  not errors of the detector, and are excluded from both sides.
- A level shift counts as detected if any of the first three months after its onset is flagged;
  Page-Hinkley counts if it alarms between 2 months before and 6 months after the onset.
- Human-LLM agreement is only meaningful once enough issues have been decided; the script reports
  how many decisions it is based on.
