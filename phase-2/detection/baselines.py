"""
Alternative baseline computation methods — task brief step 4.

Each function returns a per-feature z-like score series for ONE merchant's
sorted-by-day dataframe, using ONLY trailing/expanding information (day T's
score never uses day T's own value or any future day - shift(1) throughout,
matching the leakage-safety standard set in Phase 1).

Used by evaluation/baseline_experiments.py to compare candidate baseline
methods against the existing rolling mean/std approach BEFORE deciding
whether to change what ships. Per the task brief: "choose the simplest
method that gives materially better robustness" - not implement everything.
"""
import numpy as np
import pandas as pd

BASELINE_WINDOW = 60
EWMA_SPAN = 30


def rolling_mean_std_z(g: pd.DataFrame, feat: str) -> pd.Series:
    """The method Drift Watch ships with today (Phase 1/2 default)."""
    roll_mean = g[feat].rolling(BASELINE_WINDOW, min_periods=20).mean().shift(1)
    roll_std = g[feat].rolling(BASELINE_WINDOW, min_periods=20).std().shift(1).replace(0, np.nan)
    return (g[feat] - roll_mean) / roll_std


def rolling_median_mad_z(g: pd.DataFrame, feat: str) -> pd.Series:
    """Robust alternative: median + MAD (scaled by 1.4826 to be a consistent
    estimator of std under normality) instead of mean/std. Less sensitive to
    a single extreme outlier day inside the baseline window itself."""
    roll_median = g[feat].rolling(BASELINE_WINDOW, min_periods=20).median().shift(1)

    def mad(x):
        return np.median(np.abs(x - np.median(x)))

    roll_mad = g[feat].rolling(BASELINE_WINDOW, min_periods=20).apply(mad, raw=True).shift(1)
    roll_mad_scaled = (roll_mad * 1.4826).replace(0, np.nan)
    return (g[feat] - roll_median) / roll_mad_scaled


def ewma_z(g: pd.DataFrame, feat: str) -> pd.Series:
    """Exponentially-weighted mean/std (span=30) - reacts faster to genuine
    regime change than a flat trailing window, at the cost of being more
    sensitive to recent noise. Shifted by 1 to avoid leakage."""
    ewm_mean = g[feat].ewm(span=EWMA_SPAN, min_periods=20).mean().shift(1)
    ewm_std = g[feat].ewm(span=EWMA_SPAN, min_periods=20).std().shift(1).replace(0, np.nan)
    return (g[feat] - ewm_mean) / ewm_std


BASELINE_METHODS = {
    "rolling_mean_std": rolling_mean_std_z,
    "rolling_median_mad": rolling_median_mad_z,
    "ewma": ewma_z,
}
