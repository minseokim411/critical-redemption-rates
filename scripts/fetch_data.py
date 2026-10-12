"""
(Optional) Rebuild data/liquidity_metrics_*.csv from Yahoo Finance.

    pip install yfinance
    python scripts/fetch_data.py --out data_refetched/

The repository already ships the snapshot that produced the published results
(downloaded 2026-10-03). Re-downloading can give slightly different numbers,
because Yahoo revises its history, so this script writes to a separate folder
by default. Deterministic results do not depend on these files, because sigma
and ADV cancel under target-impact calibration. Only the Monte Carlo 90% range
uses them.

Columns per ticker
------------------
ADV_20d_usd                   20-day mean of (close x volume), in USD
Volatility_ann                20-day std of daily close-to-close returns x sqrt(252)
CS_Spread_est_REFERENCE_ONLY  Corwin-Schultz (2012) high-low spread of the ETF
                              wrapper. Diagnostic only and NOT used by the model,
                              which takes bond-market spreads from the literature.

Windows
-------
normal  2023-01-03 .. 2026-09-30
stress  2020-02-03 .. 2020-04-30   (COVID-19 bond-market stress)
Raw data start 45 business days before each window, so the 20-day rolling
measures are valid from the first day of the window.
"""

import argparse
import os

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

TICKERS = ["AGG", "HYG", "LQD"]
WINDOWS = {
    # label: (start, yfinance end (exclusive), last day kept)
    "normal": ("2023-01-01", "2026-10-01", "2026-09-30"),
    "stress_2020": ("2020-02-01", "2020-05-01", "2020-04-30"),
}
ROLLING_WINDOW = 20
LOOKBACK_BDAYS = 45


def corwin_schultz_spread(df):
    """Corwin & Schultz (2012) high-low spread estimator (reference only)."""
    hi, lo = df["High"], df["Low"]
    beta = np.log(hi / lo) ** 2 + np.log(hi.shift(1) / lo.shift(1)) ** 2
    gamma = np.log(hi.rolling(2).max() / lo.rolling(2).min()) ** 2
    denom = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)
    return (2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))).clip(lower=0)


def build_metrics(label, start, end, last_day, out_dir):
    import yfinance as yf
    raw_start = (pd.Timestamp(start) - BDay(LOOKBACK_BDAYS)).strftime("%Y-%m-%d")
    raw = yf.download(TICKERS, start=raw_start, end=end, group_by="ticker", auto_adjust=False)
    if raw is None or raw.empty:
        raise RuntimeError(f"[{label}] empty download (network / rate limit?)")
    out = {}
    for t in TICKERS:
        df = raw[t].dropna()
        full = pd.DataFrame({
            "ADV_20d_usd": (df["Close"] * df["Volume"]).rolling(ROLLING_WINDOW).mean(),
            "Volatility_ann": df["Close"].pct_change().rolling(ROLLING_WINDOW).std() * np.sqrt(252),
            "CS_Spread_est_REFERENCE_ONLY": corwin_schultz_spread(df),
        })
        out[t] = full.loc[pd.Timestamp(start):pd.Timestamp(last_day)]
    metrics = pd.concat(out, axis=1)
    metrics.index.name = "Date"
    path = os.path.join(out_dir, f"liquidity_metrics_{label}.csv")
    metrics.to_csv(path)
    n = metrics.dropna().shape[0]
    print(f"[{label}] {metrics.index.min().date()}..{metrics.index.max().date()}  "
          f"complete rows={n}  -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data_refetched", help="output folder")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for label, (start, end, last) in WINDOWS.items():
        build_metrics(label, start, end, last, args.out)


if __name__ == "__main__":
    main()
