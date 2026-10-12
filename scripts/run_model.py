"""
Run the full model and write every result table to outputs/tables/.

    python scripts/run_model.py

This script is deterministic: the Monte Carlo uses a fixed seed. Every number
quoted in the README comes from one of the files it writes.
"""

import contextlib
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from crr import config as C                      # noqa: E402
from crr import model as M                       # noqa: E402
from crr import uncertainty as U                 # noqa: E402
from crr.agg_target import derive_agg_target, OTHER_REPORTED_WEIGHT, AGG_COMPONENTS  # noqa: E402

DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "outputs", "tables")
REGIMES, METHODS = M.REGIMES, M.METHODS


def save(df, name):
    path = os.path.join(OUT, name)
    df.to_csv(path, index=False)
    print(f"  wrote outputs/tables/{name}")


@contextlib.contextmanager
def scaled_normal_targets(k):
    """Temporarily multiply every normal-regime target impact by k (supplementary)."""
    names = ["AGG_TARGET_NORMAL", "LQD_TARGET_NORMAL", "HYG_TARGET_NORMAL"]
    old = {n: getattr(C, n) for n in names}
    try:
        for n in names:
            setattr(C, n, old[n] * k)
        yield
    finally:
        for n in names:
            setattr(C, n, old[n])


def main():
    os.makedirs(OUT, exist_ok=True)
    normal_df = M.load_metrics_csv(os.path.join(DATA, "liquidity_metrics_normal.csv"))
    stress_df = M.load_metrics_csv(os.path.join(DATA, "liquidity_metrics_stress_2020.csv"))
    aum = C.TOTAL_AUM

    # ---- 0. Inputs and diagnostics -------------------------------------------
    print("Inputs")
    tickers = sorted({t for w in C.PORTFOLIOS.values() for t in w})
    diag = []
    for t in tickers:
        sig, adv, day = M.stress_pair_joint(stress_df, t)
        diag.append({
            "ticker": t,
            "normal_obs": int(normal_df[(t, "ADV_20d_usd")].notna().sum()),
            "stress_obs": int(stress_df[(t, "ADV_20d_usd")].notna().sum()),
            "normal_sigma_mean": M.normal_value(normal_df, t, "Volatility_ann"),
            "normal_adv_mean_usd": M.normal_value(normal_df, t, "ADV_20d_usd"),
            "stress_joint_date": day.date().isoformat(),
            "stress_sigma": sig, "stress_adv_usd": adv,
        })
    save(pd.DataFrame(diag), "input_diagnostics.csv")

    inputs = []
    for t in tickers:
        for reg in REGIMES:
            inputs.append({"ticker": t, "regime": reg,
                           "target_impact_T": M.target_impact(t, reg),
                           "full_spread_s": C.SPREADS[t][reg]})
    save(pd.DataFrame(inputs), "model_inputs.csv")

    comp, sleeve, totals = derive_agg_target()
    save(comp, "agg_target_components.csv")
    sleeve["T_AGG_derived"] = sleeve["regime"].map(totals)
    sleeve["T_AGG_adopted"] = sleeve["regime"].map(
        {"normal": C.AGG_TARGET_NORMAL, "stress": C.AGG_TARGET_STRESS})
    sleeve["other_reported_weight"] = OTHER_REPORTED_WEIGHT
    sleeve["other_listed_items_sum"] = sum(w for _, s, w, _ in AGG_COMPONENTS if s == "Other")
    save(sleeve, "agg_target_sleeves.csv")

    # ---- 1. Curves and critical metrics at the baseline AUM ------------------
    print("Baseline (AUM = USD 500M)")
    params = {name: M.build_asset_params(list(w), normal_df, stress_df)
              for name, w in C.PORTFOLIOS.items()}

    curve_rows, crit_rows, peak_rows = [], [], []
    for name, w in C.PORTFOLIOS.items():
        ap = params[name]
        x_d = M.liquidity_depletion_threshold(w)
        crit = {"portfolio": name, "x_D": x_d}
        for method in METHODS:
            for reg in REGIMES:
                crit[f"x2pct_{method}_{reg}"] = M.benchmark_crossing(ap, w, aum, method, reg)
                R, Mm = M.compute_loss_curve(ap, w, aum, method, reg)
                E = M.excess_cost_curve(ap, w, aum, method, reg)
                with np.errstate(divide="ignore", invalid="ignore"):
                    rho = np.where(C.X_GRID > 0, R / (C.X_GRID * aum), np.nan)
                for x, r, mm, rh, e in zip(C.X_GRID, R, Mm, rho, E):
                    curve_rows.append({"method": method, "portfolio": name, "regime": reg,
                                       "x": round(float(x), 4), "R": r, "M": mm, "L": r + mm,
                                       "rho": rh, "E": e})
                peak_rows.append({"portfolio": name, "method": method, "regime": reg,
                                  "E_at_x100": float(E[-1])})
        for reg in REGIMES:
            wf, pr = crit[f"x2pct_waterfall_{reg}"], crit[f"x2pct_pro_rata_{reg}"]
            crit[f"gap_pp_{reg}"] = (wf - pr) * 100
            crit[f"multiple_{reg}"] = wf / pr
        crit_rows.append(crit)
    save(pd.DataFrame(crit_rows), "critical_metrics.csv")
    save(pd.DataFrame(curve_rows), "loss_curves.csv")
    save(pd.DataFrame(peak_rows), "excess_cost_at_full_redemption.csv")

    # ---- 2. Headline losses + Monte Carlo + stress-assumption range ----------
    print("Headline losses and uncertainty ranges")
    head, samples = [], []
    for name, w in C.PORTFOLIOS.items():
        ap = params[name]
        x_d = M.liquidity_depletion_threshold(w)
        r, m = M.compute_R_M(ap, w, x_d, aum, "waterfall", "normal")
        R, Mm = M.compute_loss_curve(ap, w, aum, "pro_rata", "normal")
        L = R + Mm
        k = int(np.argmax(L))
        mc_w = U.mc_loss_at_rate(ap, normal_df, w, aum, "waterfall", x_d)
        mc_p = U.mc_peak_loss(ap, normal_df, w, aum, "pro_rata")
        sa_w = U.stress_assumption_range(normal_df, stress_df, w, aum, "waterfall", x_eval=x_d)
        sa_p = U.stress_assumption_range(normal_df, stress_df, w, aum, "pro_rata")
        head.append({
            "portfolio": name, "aum": aum, "loss_type": "R_plus_M", "regime": "normal",
            "waterfall_x_eval": x_d, "waterfall_L": r + m,
            "prorata_x_peak": float(C.X_GRID[k]), "prorata_L_peak": float(L[k]),
            "waterfall_mc_p5": mc_w["p5"], "waterfall_mc_p50": mc_w["p50"], "waterfall_mc_p95": mc_w["p95"],
            "prorata_mc_p5": mc_p["p5"], "prorata_mc_p50": mc_p["p50"], "prorata_mc_p95": mc_p["p95"],
            "waterfall_stress_assumption_min": sa_w["min"], "waterfall_stress_assumption_max": sa_w["max"],
            "prorata_stress_assumption_min": sa_p["min"], "prorata_stress_assumption_max": sa_p["max"],
        })
        for i, (a, b) in enumerate(zip(mc_w["samples"], mc_p["samples"])):
            samples.append({"portfolio": name, "draw": i, "waterfall_L_at_xD": a, "prorata_peak_L": b})
    save(pd.DataFrame(head), "headline_losses.csv")
    save(pd.DataFrame(samples), "mc_samples.csv")

    # ---- 3. AUM sensitivity --------------------------------------------------
    print("AUM sensitivity")
    rows = []
    for a in C.AUM_SENSITIVITY_LIST:
        for name, w in C.PORTFOLIOS.items():
            ap = params[name]
            x_d = M.liquidity_depletion_threshold(w)
            r, m = M.compute_R_M(ap, w, x_d, a, "waterfall", "normal")
            R, Mm = M.compute_loss_curve(ap, w, a, "pro_rata", "normal")
            row = {"aum": a, "portfolio": name, "x_D": x_d,
                   "waterfall_L_at_xD_normal": r + m, "prorata_L_peak_normal": float(np.max(R + Mm))}
            for method in METHODS:
                for reg in REGIMES:
                    row[f"x2pct_{method}_{reg}"] = M.benchmark_crossing(ap, w, a, method, reg)
            rows.append(row)
    save(pd.DataFrame(rows), "aum_sensitivity.csv")

    # ---- 4. p-sensitivity ------------------------------------------------------
    print("p-sensitivity")
    rows = []
    for name, w in C.PORTFOLIOS.items():
        ap = params[name]
        for method in METHODS:
            for p in C.P_GRID:
                R, Mm = M.compute_loss_curve(ap, w, aum, method, "normal", p=p)
                for x, r, mm in zip(C.X_GRID, R, Mm):
                    rows.append({"portfolio": name, "method": method, "regime": "normal", "p": p,
                                 "x": round(float(x), 4), "R": r, "M": mm, "L": r + mm})
    save(pd.DataFrame(rows), "p_sensitivity.csv")

    # ---- 5. Selling-order checks --------------------------------------------
    print("Selling-order checks")
    weight_sets = {
        "baseline 0.90/0.65/0.35": {"AGG": 0.90, "LQD": 0.65, "HYG": 0.35},
        "same order 0.51/0.50/0.49": {"AGG": 0.51, "LQD": 0.50, "HYG": 0.49},
        "same order 0.99/0.02/0.01": {"AGG": 0.99, "LQD": 0.02, "HYG": 0.01},
        "reversed 0.35/0.65/0.90": {"AGG": 0.35, "LQD": 0.65, "HYG": 0.90},
    }
    rows = []
    for name, w in C.PORTFOLIOS.items():
        ap = params[name]
        R0, M0 = M.compute_loss_curve(ap, w, aum, "waterfall", "normal")
        for label, hw in weight_sets.items():
            order = sorted(hw, key=lambda t: -hw[t])
            R1, M1 = M.compute_loss_curve(ap, w, aum, "waterfall", "normal", order=order)
            d = (R1 + M1) - (R0 + M0)
            k = int(np.argmax(np.abs(d)))
            rows.append({"portfolio": name, "weights": label, "order": "->".join(order),
                         "max_abs_diff_L_usd": float(abs(d[k])), "at_x": float(C.X_GRID[k])})
    save(pd.DataFrame(rows), "selling_order_check.csv")

    # ---- 6. Supplementary: scale all normal target impacts --------------------
    # Not part of the presentation. It shows how strongly the results depend
    # on the literature target impacts T_i, which this model does not validate.
    print("Supplementary: target-impact scaling")
    rows = []
    for k in [0.5, 0.75, 1.0, 1.5, 2.0]:
        with scaled_normal_targets(k):
            for name, w in C.PORTFOLIOS.items():
                ap = M.build_asset_params(list(w), normal_df, stress_df)
                x_d = M.liquidity_depletion_threshold(w)
                r, m = M.compute_R_M(ap, w, x_d, aum, "waterfall", "normal")
                R, Mm = M.compute_loss_curve(ap, w, aum, "pro_rata", "normal")
                rows.append({"T_scale": k, "portfolio": name,
                             "x2pct_waterfall_normal": M.benchmark_crossing(ap, w, aum, "waterfall", "normal"),
                             "x2pct_pro_rata_normal": M.benchmark_crossing(ap, w, aum, "pro_rata", "normal"),
                             "waterfall_L_at_xD_normal": r + m,
                             "prorata_L_peak_normal": float(np.max(R + Mm))})
    save(pd.DataFrame(rows), "supplementary_target_scaling.csv")
    print("Done.")


if __name__ == "__main__":
    main()
