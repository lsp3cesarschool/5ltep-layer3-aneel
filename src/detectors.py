"""Stage 1 of 5L-TEP Layer 3: automated statistical monitoring.

Four detectors vote on every month of a series; a month is a candidate
anomaly when at least ENSEMBLE_MIN_VOTES of them agree. Page-Hinkley runs
alongside to tell sustained drift (a level shift) apart from point anomalies.

All detectors work on log(series): counts and fine totals are heavy-tailed
(one fine can exceed R$ 4 billion), and the log keeps a single month from
dominating the scale.

Each detector returns (score, threshold); a month is flagged when
score > threshold, and score/threshold feeds the ensemble score.
"""

import logging

import numpy as np
import pandas as pd

from src import config

logger = logging.getLogger(__name__)

DETECTORS = ("zscore", "mad", "iforest", "lstm_ed")


def _transform(values: pd.Series) -> np.ndarray:
    """Scale-invariant log; zeros get a floor of half the smallest positive value.

    Plain log (not log1p) matters for money converted from old currencies:
    values can be fractions of a Real, and log1p would flatten them, while
    log turns a currency conversion into a constant shift and hyperinflation
    into a smooth trend.
    """
    v = np.clip(values.to_numpy(dtype=float), 0, None)
    positive = v[v > 0]
    floor = positive.min() / 2 if len(positive) else 1.0
    return np.log(np.maximum(v, floor))


def rolling_zscore(x: np.ndarray, window: int, k: float) -> tuple[np.ndarray, float]:
    """|z| of each point against the mean/std of the previous `window` points."""
    s = pd.Series(x)
    base = s.shift(1).rolling(window, min_periods=window)
    std = base.std().to_numpy()
    std = np.where(std > 1e-9, std, np.nan)
    z = np.abs((x - base.mean().to_numpy()) / std)
    return np.nan_to_num(z, nan=0.0), k


def rolling_mad(x: np.ndarray, window: int, k: float) -> tuple[np.ndarray, float]:
    """Modified z-score (Iglewicz & Hoaglin) against the previous `window` points."""
    s = pd.Series(x)
    prev = s.shift(1)
    med = prev.rolling(window, min_periods=window).median().to_numpy()
    mad = prev.rolling(window, min_periods=window).apply(
        lambda w: np.median(np.abs(w - np.median(w))), raw=True
    ).to_numpy()
    # MAD collapses to 0 on flat windows; fall back to the mean absolute
    # deviation scaled to the same consistency constant.
    meanad = prev.rolling(window, min_periods=window).apply(
        lambda w: np.mean(np.abs(w - np.mean(w))), raw=True
    ).to_numpy()
    scale = np.where(mad > 1e-9, mad, meanad * 1.2533)
    scale = np.where(scale > 1e-9, scale, np.nan)
    m = np.abs(0.6745 * (x - med) / scale)
    return np.nan_to_num(m, nan=0.0), k


def _features(x: np.ndarray, window: int) -> np.ndarray:
    s = pd.Series(x)
    diff = s.diff().fillna(0.0)
    resid = (s - s.shift(1).rolling(window, min_periods=1).median()).fillna(0.0)
    return np.column_stack([x, diff.to_numpy(), resid.to_numpy()])


def isolation_forest(x: np.ndarray, window: int, contamination: float, seed: int) -> tuple[np.ndarray, float]:
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=seed)
    feats = _features(x, window)
    model.fit(feats)
    score = -model.score_samples(feats)  # higher = more anomalous, in (0, 1)
    return score, float(-model.offset_)


def lstm_autoencoder(
    x: np.ndarray, window: int, units: int, dropout: float, epochs: int, percentile: float, seed: int
) -> tuple[np.ndarray, float]:
    """LSTM encoder-decoder (Malhotra et al., 2016) reconstruction error.

    Trained on every sliding window of the (standardised) series; the error of
    a month is the mean squared error over all windows that contain it. The
    threshold is the given percentile of those errors.
    """
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)

    mu, sd = x.mean(), x.std() or 1.0
    z = (x - mu) / sd
    n = len(z)
    if n < window * 2:
        return np.zeros(n), float("inf")
    windows = np.stack([z[i : i + window] for i in range(n - window + 1)])
    data = torch.tensor(windows, dtype=torch.float32).unsqueeze(-1)

    class EncDec(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = nn.LSTM(1, units, batch_first=True)
            self.drop = nn.Dropout(dropout)
            self.dec = nn.LSTM(units, units, batch_first=True)
            self.out = nn.Linear(units, 1)

        def forward(self, seq):
            _, (h, _) = self.enc(seq)
            code = self.drop(h[-1]).unsqueeze(1).repeat(1, seq.shape[1], 1)
            dec, _ = self.dec(code)
            return self.out(dec)

    model = EncDec()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    gen = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(len(data), generator=gen)
        for start in range(0, len(data), 32):
            batch = data[perm[start : start + 32]]
            opt.zero_grad()
            loss = loss_fn(model(batch), batch)
            loss.backward()
            opt.step()

    model.eval()
    with torch.no_grad():
        sq = ((model(data) - data) ** 2).squeeze(-1).numpy()
    total = np.zeros(n)
    count = np.zeros(n)
    for i in range(len(windows)):
        total[i : i + window] += sq[i]
        count[i : i + window] += 1
    err = total / count
    return err, float(np.percentile(err, percentile))


def page_hinkley(x: np.ndarray, delta: float, lam: float) -> list[dict]:
    """Two-sided Page-Hinkley test for sustained mean shifts (Page, 1954).

    The series is scaled by a robust estimate of its month-to-month noise so
    that `delta` and `lam` are expressed in noise units. The cumulative sum
    restarts after each detection. Returns one dict per change point with the
    alarm and the estimated onset (where the cumulative deviation started to
    build; seasonality can pull this estimate a few months early).
    """
    diffs = np.diff(x)
    noise = 1.4826 * np.median(np.abs(diffs - np.median(diffs))) if len(diffs) else 1.0
    y = x / (noise if noise > 1e-9 else 1.0)
    points = []
    start = 0
    while start < len(y) - 1:
        mean = 0.0
        m_up = m_down = 0.0
        min_up = max_down = 0.0
        arg_up = arg_down = start
        fired = None
        for t in range(start, len(y)):
            n = t - start + 1
            mean += (y[t] - mean) / n
            m_up += y[t] - mean - delta
            m_down += y[t] - mean + delta
            if m_up < min_up:
                min_up, arg_up = m_up, t
            if m_down > max_down:
                max_down, arg_down = m_down, t
            if m_up - min_up > lam:
                fired = (t, "up", arg_up + 1)
                break
            if max_down - m_down > lam:
                fired = (t, "down", arg_down + 1)
                break
        if fired is None:
            break
        t, direction, onset = fired
        points.append({"index": int(min(onset, t)), "alarm_index": int(t), "direction": direction})
        start = t + 1
    return points


def run_detectors(series: pd.Series) -> tuple[pd.DataFrame, list[dict]]:
    """Run the ensemble and Page-Hinkley on one monthly series.

    Returns a frame indexed by month with each detector's score, threshold
    and vote, plus the ensemble vote count, flag and score; and the list of
    drift points.
    """
    x = _transform(series)
    w = config.BASELINE_WINDOW
    results = {
        "zscore": rolling_zscore(x, w, config.ZSCORE_K),
        "mad": rolling_mad(x, w, config.MAD_K),
        "iforest": isolation_forest(x, w, config.IF_CONTAMINATION, config.RANDOM_SEED),
    }
    try:
        results["lstm_ed"] = lstm_autoencoder(
            x,
            config.LSTM_WINDOW,
            config.LSTM_UNITS,
            config.LSTM_DROPOUT,
            config.LSTM_EPOCHS,
            config.LSTM_PERCENTILE,
            config.RANDOM_SEED,
        )
    except ImportError:
        logger.warning("PyTorch not installed: LSTM-ED abstains (ensemble of 3)")
        results["lstm_ed"] = (np.zeros(len(x)), float("inf"))

    out = pd.DataFrame(index=series.index)
    out["value"] = series.to_numpy()
    ratios = []
    for name in DETECTORS:
        score, thr = results[name]
        out[f"{name}_score"] = np.round(score, 6)
        out[f"{name}_vote"] = score > thr
        ratio = np.clip(score / thr, 0, 2) / 2 if np.isfinite(thr) and thr > 0 else np.zeros(len(x))
        ratios.append(ratio)
    out["votes"] = out[[f"{d}_vote" for d in DETECTORS]].sum(axis=1)
    out["anomaly"] = out["votes"] >= config.ENSEMBLE_MIN_VOTES
    # Ensemble score in [0, 1]: 0.5 means "exactly at the threshold" on average.
    out["ensemble_score"] = np.round(np.mean(ratios, axis=0), 4)

    drift = page_hinkley(x, config.PH_DELTA, config.PH_LAMBDA)
    for p in drift:
        p["month"] = str(series.index[p["index"]])
        p["alarm_month"] = str(series.index[p["alarm_index"]])
    tol = config.DRIFT_TOLERANCE_MONTHS
    spans = [(p["index"] - tol, p["alarm_index"] + tol) for p in drift]
    out["near_drift"] = [any(lo <= i <= hi for lo, hi in spans) for i in range(len(x))]
    thresholds = {name: results[name][1] for name in DETECTORS}
    out.attrs["thresholds"] = thresholds
    return out, drift


def detect_all(monthly: pd.DataFrame, series_names: list[str]) -> tuple[pd.DataFrame, dict]:
    """Run the detectors on every series of the profile; long-format output."""
    frames = []
    drift = {}
    for col in series_names:
        det, points = run_detectors(monthly[col])
        det.insert(0, "series", col)
        frames.append(det)
        drift[col] = points
        logger.info("%s: %d anomalies, %d drift points", col, int(det["anomaly"].sum()), len(points))
    out = pd.concat(frames)
    out.index.name = "month"
    return out, drift
