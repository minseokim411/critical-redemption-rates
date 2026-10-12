"""
Two separate kinds of uncertainty. They are reported side by side and never
combined.

(a) Monte Carlo 90% range (fixed-g, normal regime)
    Deterministic results use I_i(Q) = T_i * sqrt(Q / Q_ref), so the ETF sigma
    and ADV cancel. To see how day-to-day market conditions could move the
    cost, g_i is FIXED at its normal-regime calibration (mean sigma, mean
    ADV), and 1,000 trading days are bootstrapped from the normal window
    (2023-01-03 to 2026-09-30). The same day is used for every asset. With g
    fixed, impact becomes

        I_{i,d}(Q) = T_i * (sigma_{i,d} / sigma_bar_i)
                         * sqrt(ADV_bar_i / ADV_{i,d}) * sqrt(Q / Q_ref)

    The p5/p50/p95 of the resulting loss form the "Monte Carlo 90% range".
    It is NOT a confidence interval: the deterministic result has no data-
    estimation error, and the p50 sits below it. It is NOT VaR either: no
    returns or holding horizon are simulated. It covers the normal regime
    only, and it is conditional on T_i being correct.

    Implementation note: re-calibrating g on each draw would cancel sigma
    and ADV again and give a range of exactly zero. g must stay fixed.

(b) Stress-assumption sensitivity range
    Stress-regime loss is recomputed with the HYG (and AGG) stress target
    taken one at a time from their 5-value arrays. AGG's array holds a single
    point estimate, so in practice only HYG adds width. Portfolios or
    evaluation points that sell no HYG show min == max.
"""

import numpy as np

from . import config as C
from .model import build_asset_params, compute_R_M, compute_loss_curve


def bootstrap_common_rows(metrics_df, tickers, n_iter, rng):
    """Draw n_iter trading days (with replacement) on which every asset has data."""
    cols = [(t, c) for t in tickers for c in ("ADV_20d_usd", "Volatility_ann")]
    sub = metrics_df[cols].dropna()
    if sub.empty:
        raise ValueError("No common valid dates to bootstrap.")
    idx = rng.choice(sub.index, size=n_iter, replace=True)
    return sub.loc[idx]


def _fixed_g_params(asset_params, row, tickers):
    return {
        t: {
            "sigma_normal": row[(t, "Volatility_ann")],
            "adv_normal": row[(t, "ADV_20d_usd")],
            "g_normal": asset_params[t]["g_normal"],          # fixed, never re-calibrated
            "spread_normal": asset_params[t]["spread_normal"],
        }
        for t in tickers
    }


def _summary(values):
    v = np.asarray(values)
    return {"mean": v.mean(), "p5": np.percentile(v, 5),
            "p50": np.percentile(v, 50), "p95": np.percentile(v, 95), "samples": v}


def mc_loss_at_rate(asset_params, metrics_df, weights, total_aum, method, x_eval,
                    include_M=True, n_iter=C.N_MC_ITER, seed=C.RNG_SEED):
    """Monte Carlo 90% range of L at a fixed redemption rate (Waterfall: x_D)."""
    rng = np.random.default_rng(seed)
    tickers = list(weights)
    draws = bootstrap_common_rows(metrics_df, tickers, n_iter, rng)
    out = []
    for _, row in draws.iterrows():
        ap = _fixed_g_params(asset_params, row, tickers)
        r, m = compute_R_M(ap, weights, x_eval, total_aum, method, regime="normal")
        out.append(r + m if include_M else r)
    return _summary(out)


def mc_peak_loss(asset_params, metrics_df, weights, total_aum, method,
                 include_M=True, n_iter=C.N_MC_ITER, seed=C.RNG_SEED):
    """Monte Carlo 90% range of the peak of L(x) over x (Pro-rata: x = 100%)."""
    rng = np.random.default_rng(seed)
    tickers = list(weights)
    draws = bootstrap_common_rows(metrics_df, tickers, n_iter, rng)
    out = []
    for _, row in draws.iterrows():
        ap = _fixed_g_params(asset_params, row, tickers)
        Rs, Ms = [], []
        for x in C.X_GRID:
            r, m = compute_R_M(ap, weights, x, total_aum, method, regime="normal")
            Rs.append(r)
            Ms.append(m)
        L = np.array(Rs) + np.array(Ms) if include_M else np.array(Rs)
        out.append(L.max())
    return _summary(out)


def stress_assumption_range(normal_df, stress_df, weights, total_aum, method,
                            include_M=True, x_eval=None):
    """Min / max stress-regime loss when the AGG or HYG stress target is varied
    one at a time over its 5-value array.

    Waterfall is evaluated at x_eval (= x_D). Pro-rata is evaluated at the
    peak of its loss curve."""
    tickers = list(weights)
    scenario = [t for t in tickers if t in ("AGG", "HYG")]
    values = []

    def evaluate(ap):
        if method == "waterfall":
            r, m = compute_R_M(ap, weights, x_eval, total_aum, "waterfall", regime="stress")
            return r + m if include_M else r
        Rs, Ms = compute_loss_curve(ap, weights, total_aum, "pro_rata", regime="stress")
        return float(np.max(Rs + Ms if include_M else Rs))

    if not scenario:
        values.append(evaluate(build_asset_params(tickers, normal_df, stress_df)))
    for t in scenario:
        arr = C.AGG_TARGET_STRESS_SENSITIVITY if t == "AGG" else C.HYG_TARGET_STRESS_SENSITIVITY
        for idx in range(len(arr)):
            ap = build_asset_params(tickers, normal_df, stress_df, stress_idx_overrides={t: idx})
            values.append(evaluate(ap))
    v = np.array(values)
    return {"min": v.min(), "max": v.max(), "n_scenarios": len(v)}
