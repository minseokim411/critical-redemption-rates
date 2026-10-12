"""
Core model: liquidation schedules, price impact, losses, and critical metrics.

Notation (matches the README)
-----------------------------
x       redemption rate, the share of AUM redeemed (0-1)
w_i     portfolio weight of asset i;   H_i = w_i * AUM  (holding)
Q_i(x)  dollar amount of asset i sold to meet redemption x*AUM
I_i(Q)  price impact (fraction of price) from selling Q of asset i
s_i     full bid-ask spread of asset i
p       permanent share of impact that marks down unsold holdings

    I_i(Q)   = g_i * sigma_i * sqrt(Q / ADV_i)                 square-root impact
    g_i      = T_i / (sigma_i * sqrt(Q_ref / ADV_i))           calibrated to T_i
         =>  I_i(Q) = T_i * sqrt(Q / Q_ref)                    sigma, ADV cancel
    R_i      = (s_i / 2) * Q_i + I_i(Q_i) * Q_i                realised cost
    M_i      = p * I_i(Q_i) * (H_i - Q_i)                      mark-down of the rest
    L(x)     = sum_i [R_i + M_i]
    rho(x)   = R(x) / (x * AUM)                                liquidation-cost rate
    E(x)     = max(0, R(x) - b * x * AUM) / AUM,  b = 2%       cost above benchmark

Two critical metrics are reported. They answer different questions and are
never merged:
    x_D     liquidity depletion threshold: the redemption rate at which the
            most liquid asset (AGG) is used up under Waterfall. It depends only
            on the weights, so it is defined only for Waterfall.
    x*_2%   2% benchmark crossing: the first x at which rho(x) >= 2%. It is
            defined for both Waterfall and Pro-rata, and it depends on the
            regime and on AUM.
"""

import numpy as np
import pandas as pd

from . import config as C

REGIMES = ("normal", "stress")
METHODS = ("waterfall", "pro_rata")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_metrics_csv(path):
    """Read a liquidity-metrics CSV (two-level columns: ticker, metric)."""
    return pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)


def normal_value(metrics_df, ticker, column):
    """Normal-regime sigma / ADV: the mean over the whole normal window.

    The mean is used instead of the last observation, which would make the
    input depend on the day the script happened to run."""
    series = metrics_df[(ticker, column)].dropna()
    if series.empty:
        raise ValueError(f"No valid values for {ticker}/{column}.")
    return series.mean()


def stress_pair_joint(metrics_df, ticker, target_quantile=0.90):
    """Stress-regime (sigma, ADV) taken from ONE actual trading day.

    Taking independent percentiles of sigma and ADV could combine two days into
    a market state that never happened. Instead, each day gets a composite
    illiquidity rank, 0.5 * pct-rank(sigma) + 0.5 * (1 - pct-rank(ADV)), and
    the day closest to `target_quantile` is chosen.

    Diagnostic note: deterministic results do not depend on this choice,
    because sigma and ADV cancel under target-impact calibration."""
    sigma_s = metrics_df[(ticker, "Volatility_ann")].dropna()
    adv_s = metrics_df[(ticker, "ADV_20d_usd")].dropna()
    common = sigma_s.index.intersection(adv_s.index)
    if len(common) == 0:
        raise ValueError(f"{ticker}: no common valid dates for sigma/ADV.")
    sigma_s, adv_s = sigma_s.loc[common], adv_s.loc[common]
    composite = 0.5 * sigma_s.rank(pct=True) + 0.5 * (1.0 - adv_s.rank(pct=True))
    day = (composite - target_quantile).abs().idxmin()
    return float(sigma_s.loc[day]), float(adv_s.loc[day]), day


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
def target_impact(ticker, regime, stress_idx=C.STRESS_REPRESENTATIVE_IDX):
    """Target impact T_i (price impact per USD 1M sold)."""
    if ticker == "AGG":
        return C.AGG_TARGET_NORMAL if regime == "normal" else C.AGG_TARGET_STRESS_SENSITIVITY[stress_idx]
    if ticker == "LQD":
        return C.LQD_TARGET_NORMAL if regime == "normal" else C.LQD_TARGET_STRESS
    if ticker == "HYG":
        return C.HYG_TARGET_NORMAL if regime == "normal" else C.HYG_TARGET_STRESS_SENSITIVITY[stress_idx]
    raise ValueError(f"Unknown ticker {ticker}")


def calibrate_g(sigma, adv, target, q_ref=C.Q_REF):
    """Solve g so that g * sigma * sqrt(q_ref / adv) == target."""
    denom = sigma * np.sqrt(q_ref / adv)
    if denom <= 0:
        raise ValueError("sigma and ADV must be positive to calibrate g.")
    return target / denom


def build_asset_params(tickers, normal_df, stress_df, stress_idx_overrides=None):
    """Per-asset sigma, ADV, calibrated g, target T and spread for both regimes."""
    stress_idx_overrides = stress_idx_overrides or {}
    params = {}
    for t in tickers:
        sigma_n = normal_value(normal_df, t, "Volatility_ann")
        adv_n = normal_value(normal_df, t, "ADV_20d_usd")
        sigma_s, adv_s, _ = stress_pair_joint(stress_df, t, target_quantile=0.90)
        idx = stress_idx_overrides.get(t, C.STRESS_REPRESENTATIVE_IDX)
        t_n = target_impact(t, "normal")
        t_s = target_impact(t, "stress", stress_idx=idx)
        params[t] = {
            "sigma_normal": sigma_n, "adv_normal": adv_n,
            "sigma_stress": sigma_s, "adv_stress": adv_s,
            "g_normal": calibrate_g(sigma_n, adv_n, t_n),
            "g_stress": calibrate_g(sigma_s, adv_s, t_s),
            "target_normal": t_n, "target_stress": t_s,
            "spread_normal": C.SPREADS[t]["normal"],
            "spread_stress": C.SPREADS[t]["stress"],
        }
    return params


# ---------------------------------------------------------------------------
# Liquidation rules
# ---------------------------------------------------------------------------
def liquidation_schedule(weights, x, total_aum, method, order=None):
    """Dollar amount Q_i sold of each asset to meet a redemption of x * AUM.

    pro_rata : sell every asset in proportion to its weight, Q_i = x * H_i.
    waterfall: sell assets fully in liquidity order (AGG -> LQD -> HYG)
               until the redemption is met.
    """
    order = order or C.LIQUIDITY_ORDER
    holdings = {t: w * total_aum for t, w in weights.items()}
    if method == "pro_rata":
        return {t: x * h for t, h in holdings.items()}
    if method == "waterfall":
        remaining = x * total_aum
        sold = {t: 0.0 for t in weights}
        for t in order:
            if t not in weights:
                continue
            take = min(holdings[t], remaining)
            sold[t] = take
            remaining -= take
            if remaining <= 1e-9:
                break
        return sold
    raise ValueError(f"Unknown liquidation method: {method}")


def liquidity_depletion_points(weights, order=None):
    """Cumulative redemption rates at which each asset is used up (Waterfall)."""
    order = order or C.LIQUIDITY_ORDER
    cum, points = 0.0, []
    for t in order:
        if t in weights:
            cum += weights[t]
            points.append((t, cum))
    return points


def liquidity_depletion_threshold(weights, order=None):
    """x_D: redemption rate at which the first (most liquid) asset is used up.

    It is a structural quantity that depends only on the weights. It does not
    use market data, impact or spreads, so no Monte Carlo range applies to it."""
    return liquidity_depletion_points(weights, order)[0][1]


# ---------------------------------------------------------------------------
# Losses
# ---------------------------------------------------------------------------
def compute_R_M(asset_params, weights, x, total_aum, method, regime="normal",
                p=None, order=None):
    """Realised cost R and mark-down of unsold holdings M at redemption rate x.

    The execution impact (in R) and the persistent impact (in M) both use the
    same I_i(Q_i), because separate calibration data are not available. Only
    the share p of it is assumed to persist on the unsold holdings."""
    p = C.PERMANENT_IMPACT_FRAC if p is None else p
    Q = liquidation_schedule(weights, x, total_aum, method, order)
    R_total, M_total = 0.0, 0.0
    for t, w in weights.items():
        a = asset_params[t]
        sigma, adv = a[f"sigma_{regime}"], a[f"adv_{regime}"]
        g, spread = a[f"g_{regime}"], a[f"spread_{regime}"]
        Qi = Q[t]
        impact = g * sigma * np.sqrt(Qi / adv) if Qi > 0 else 0.0   # I_i(Q_i)
        R_total += spread / 2 * Qi + impact * Qi
        M_total += p * impact * (w * total_aum - Qi)
    return R_total, M_total


def compute_loss_curve(asset_params, weights, total_aum, method, regime="normal",
                       x_grid=None, p=None, order=None):
    """Arrays R(x), M(x) over the redemption grid."""
    x_grid = C.X_GRID if x_grid is None else x_grid
    Rs, Ms = [], []
    for x in x_grid:
        r, m = compute_R_M(asset_params, weights, x, total_aum, method, regime, p, order)
        Rs.append(r)
        Ms.append(m)
    return np.array(Rs), np.array(Ms)


# ---------------------------------------------------------------------------
# Benchmark metrics
# ---------------------------------------------------------------------------
def benchmark_crossing(asset_params, weights, total_aum, method, regime="normal",
                       x_grid=None, b=C.BENCHMARK_2PCT):
    """x*_2%: first x (0.05 pp grid) with rho(x) = R(x)/(x*AUM) >= b.

    The denominator x*AUM is the amount redeemed, so rho is "cost per dollar
    redeemed". M is excluded because it is a mark-down of holdings that are
    not sold. Returns NaN if rho never reaches b up to x = 100%."""
    x_grid = C.X_GRID_FINE if x_grid is None else x_grid
    for x in x_grid:
        if x <= 0:
            continue
        r, _ = compute_R_M(asset_params, weights, x, total_aum, method, regime)
        if r / (x * total_aum) >= b:
            return float(x)
    return np.nan


def excess_cost_curve(asset_params, weights, total_aum, method, regime="normal",
                      x_grid=None, b=C.BENCHMARK_2PCT):
    """E(x) = max(0, R(x) - b*x*AUM) / AUM, the cost above the 2% benchmark.

    E(x) is an interpretive metric derived from R. It is not part of the loss
    function. This study reads it as dilution borne by remaining investors.
    The denominator is pre-redemption AUM, which is conservative: the burden
    per remaining dollar is E(x) / (1 - x)."""
    x_grid = C.X_GRID if x_grid is None else x_grid
    out = np.zeros_like(x_grid, dtype=float)
    for i, x in enumerate(x_grid):
        if x <= 0:
            continue
        r, _ = compute_R_M(asset_params, weights, x, total_aum, method, regime)
        out[i] = max(0.0, r - b * x * total_aum) / total_aum
    return out
