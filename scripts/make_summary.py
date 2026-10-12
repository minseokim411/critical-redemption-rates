"""
Format the result tables as Markdown (outputs/results_summary.md).

    python scripts/make_summary.py            # write the summary
    python scripts/make_summary.py --sync     # also update the README results block

Every table in the README "Results" section is generated here from
outputs/tables/*.csv. `tests/test_readme_sync.py` fails if the README block and
this generator ever disagree.
"""

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAB = os.path.join(ROOT, "outputs", "tables")
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
SHORT = {"A_aggressive": "A", "B_moderate": "B", "C_conservative": "C"}


def pct(v, d=2):
    return "—" if pd.isna(v) else f"{v * 100:.{d}f}%"


def usd_m(v):
    return f"{v / 1e6:,.2f}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def build(include_supplementary=True):
    t = lambda f: pd.read_csv(os.path.join(TAB, f))   # noqa: E731
    crit, head = t("critical_metrics.csv"), t("headline_losses.csv")
    aum, exc = t("aum_sensitivity.csv"), t("excess_cost_at_full_redemption.csv")
    sleeves, order = t("agg_target_sleeves.csv"), t("selling_order_check.csv")
    inputs, scal = t("model_inputs.csv"), t("supplementary_target_scaling.csv")
    s = []

    s.append("#### Model inputs (per asset)\n")
    rows = []
    for tk in ["AGG", "LQD", "HYG"]:
        d = inputs[inputs.ticker == tk].set_index("regime")
        rows.append([tk, pct(d.loc["normal", "target_impact_T"], 4), pct(d.loc["stress", "target_impact_T"], 4),
                     pct(d.loc["normal", "full_spread_s"], 4), pct(d.loc["stress", "full_spread_s"], 4)])
    s.append(table(["Asset", "T normal", "T stress", "s normal", "s stress"], rows))

    s.append("\n\n#### AGG bottom-up target impact (share of T_AGG by sleeve)\n")
    rows = []
    for sl in ["Treasury", "Agency MBS", "IG Corporate", "Other"]:
        n = sleeves[(sleeves.regime == "normal") & (sleeves.sleeve == sl)].iloc[0]
        st = sleeves[(sleeves.regime == "stress") & (sleeves.sleeve == sl)].iloc[0]
        rows.append([sl, pct(n.weight), pct(n.contribution_share, 1), pct(st.contribution_share, 1)])
    n0 = sleeves[sleeves.regime == "normal"].iloc[0]
    s0 = sleeves[sleeves.regime == "stress"].iloc[0]
    rows.append(["**T_AGG (derived / adopted)**", "", f"{pct(n0.T_AGG_derived, 4)} / {pct(n0.T_AGG_adopted, 4)}",
                 f"{pct(s0.T_AGG_derived, 4)} / {pct(s0.T_AGG_adopted, 4)}"])
    s.append(table(["Sleeve", "Weight", "Share of T_AGG (normal)", "Share of T_AGG (stress)"], rows))
    s.append(f"\n\n*The listed 'Other' sub-items sum to {pct(n0.other_listed_items_sum)}, "
             f"not the reported {pct(n0.other_reported_weight)} (see Limitations).*")

    s.append("\n\n#### Critical metrics (AUM = USD 500M)\n")
    rows = []
    for _, r in crit.iterrows():
        rows.append([SHORT[r.portfolio], pct(r.x_D, 1),
                     pct(r.x2pct_waterfall_normal), pct(r.x2pct_waterfall_stress),
                     pct(r.x2pct_pro_rata_normal), pct(r.x2pct_pro_rata_stress)])
    s.append(table(["Portfolio", "x_D (Waterfall)", "x*₂% Waterfall, normal", "x*₂% Waterfall, stress",
                    "x*₂% Pro-rata, normal", "x*₂% Pro-rata, stress"], rows))

    s.append("\n\n#### Waterfall vs Pro-rata gap in x*₂%\n")
    rows = []
    for reg in ["normal", "stress"]:
        for _, r in crit.iterrows():
            rows.append([SHORT[r.portfolio], reg, f"{r[f'gap_pp_{reg}']:.2f} pp", f"{r[f'multiple_{reg}']:.1f}×"])
    s.append(table(["Portfolio", "Regime", "Waterfall − Pro-rata", "Waterfall ÷ Pro-rata"], rows))

    s.append("\n\n#### Losses, Monte Carlo 90% range and stress-assumption range (USD millions, R + M, AUM = USD 500M)\n")
    rows = []
    for _, r in head.iterrows():
        rows.append([SHORT[r.portfolio],
                     f"{usd_m(r.waterfall_L)} (x={pct(r.waterfall_x_eval, 0)})",
                     f"{usd_m(r.waterfall_mc_p5)} – {usd_m(r.waterfall_mc_p95)} (p50 {usd_m(r.waterfall_mc_p50)})",
                     f"{usd_m(r.prorata_L_peak)} (x={pct(r.prorata_x_peak, 0)})",
                     f"{usd_m(r.prorata_mc_p5)} – {usd_m(r.prorata_mc_p95)} (p50 {usd_m(r.prorata_mc_p50)})",
                     f"{usd_m(r.waterfall_stress_assumption_min)} – {usd_m(r.waterfall_stress_assumption_max)}",
                     f"{usd_m(r.prorata_stress_assumption_min)} – {usd_m(r.prorata_stress_assumption_max)}"])
    s.append(table(["Portfolio", "Waterfall L at x_D (normal)", "Waterfall MC 90% range",
                    "Pro-rata peak L (normal)", "Pro-rata MC 90% range",
                    "Waterfall stress-assumption range", "Pro-rata stress-assumption range"], rows))

    s.append("\n\n#### Cost above the 2% benchmark at full redemption, E(100%)\n")
    rows = []
    for p in SHORT:
        d = exc[(exc.portfolio == p) & (exc.method == "waterfall")].set_index("regime")
        rows.append([SHORT[p], pct(d.loc["normal", "E_at_x100"]), pct(d.loc["stress", "E_at_x100"])])
    s.append(table(["Portfolio", "Normal", "Stress"], rows))
    s.append("\n\n*Identical for Waterfall and Pro-rata: at x = 100% both sell every holding.*")

    s.append("\n\n#### AUM sensitivity of x*₂% (AUM in USD; W = Waterfall, PR = Pro-rata; — = never reaches 2%)\n")
    rows = []
    for p in SHORT:
        for reg in ["normal", "stress"]:
            row = [SHORT[p], reg]
            for a in sorted(aum.aum.unique()):
                r = aum[(aum.aum == a) & (aum.portfolio == p)].iloc[0]
                row += [pct(r[f"x2pct_waterfall_{reg}"]), pct(r[f"x2pct_pro_rata_{reg}"])]
            rows.append(row)
    hdr = ["Portfolio", "Regime"]
    for a in sorted(aum.aum.unique()):
        lab = f"{a / 1e9:g}B" if a >= 1e9 else f"{a / 1e6:g}M"
        hdr += [f"{lab} W", f"{lab} PR"]
    s.append(table(hdr, rows))

    s.append("\n\n#### Selling-order check (Waterfall, normal regime; largest absolute change in L(x) vs the baseline order)\n")
    rows = []
    for p in SHORT:
        d = order[order.portfolio == p]
        same = d[d.weights.str.startswith("same order")].max_abs_diff_L_usd.max()
        rev = d[d.weights.str.startswith("reversed")].iloc[0]
        rows.append([SHORT[p], f"USD {same:,.0f}", f"USD {rev.max_abs_diff_L_usd:,.0f} (at x = {pct(rev.at_x, 1)})"])
    s.append(table(["Portfolio", "Same order, different magnitudes (0.51/0.50/0.49, 0.99/0.02/0.01)",
                    "Reversed order HYG -> LQD -> AGG"], rows))
    if not include_supplementary:
        return "\n".join(s) + "\n"
    s.append("\n\n#### Supplementary (not in the presentation): scaling every normal-regime T_i\n")
    rows = []
    for _, r in scal.iterrows():
        rows.append([f"{r.T_scale:g}×", SHORT[r.portfolio], pct(r.x2pct_waterfall_normal),
                     pct(r.x2pct_pro_rata_normal), usd_m(r.waterfall_L_at_xD_normal), usd_m(r.prorata_L_peak_normal)])
    s.append(table(["T scale", "Portfolio", "x*₂% Waterfall", "x*₂% Pro-rata",
                    "Waterfall L at x_D (USD M)", "Pro-rata peak L (USD M)"], rows))
    return "\n".join(s) + "\n"


def main():
    md = build()
    with open(os.path.join(ROOT, "outputs", "results_summary.md"), "w") as f:
        f.write("# Results summary (generated by scripts/make_summary.py — do not edit by hand)\n\n" + md)
    print("  wrote outputs/results_summary.md")
    if "--sync" in sys.argv:
        path = os.path.join(ROOT, "README.md")
        text = open(path).read()
        i, j = text.index(START) + len(START), text.index(END)
        open(path, "w").write(text[:i] + "\n" + build(include_supplementary=False) + text[j:])
        print("  synced README.md results block")


if __name__ == "__main__":
    main()
