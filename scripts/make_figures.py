"""
Draw every figure in outputs/figures/ from the tables written by run_model.py.

    python scripts/make_figures.py

The figures read only outputs/tables/*.csv, so they cannot drift from the
numbers in the tables.
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
import pandas as pd                      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAB = os.path.join(ROOT, "outputs", "tables")
FIG = os.path.join(ROOT, "outputs", "figures")

# Categorical slots 1-3 of a colour-blind-validated palette (fixed order).
PORT = {
    "A_aggressive":   ("A (aggressive, HY 20%)", "#2a78d6"),
    "B_moderate":     ("B (moderate, HY 10%)",   "#eb6834"),
    "C_conservative": ("C (conservative, HY 0%)", "#1baf7a"),
}
P_COLORS = ["#cde3fb", "#6aa7ea", "#2a75d8", "#1c4f95", "#0f3263"]   # p = 0 -> 1 (sequential)
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3de", "#ffffff"
METHOD_LABEL = {"waterfall": "Waterfall (AGG -> LQD -> HYG)", "pro_rata": "Pro-rata (all assets pro rata)"}
REGIME_LABEL = {"normal": "Normal (2023-26 calibration)", "stress": "Stress (2020 calibration)"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9.5,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "legend.frameon": False, "lines.linewidth": 2.0,
})


def footnote(fig, text):
    fig.text(0.01, 0.005, text, fontsize=7.8, color=INK2, ha="left", va="bottom")


def save(fig, name):
    fig.savefig(os.path.join(FIG, name), dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote outputs/figures/{name}")


def grid_2x2(curves, value, ylabel, title, note, hline=None, crit=None, mark_xd=False):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4), sharex=True)
    for i, method in enumerate(["waterfall", "pro_rata"]):
        for j, regime in enumerate(["normal", "stress"]):
            ax = axes[i, j]
            for port, (label, color) in PORT.items():
                d = curves[(curves.method == method) & (curves.regime == regime) & (curves.portfolio == port)]
                ax.plot(d.x * 100, value(d), color=color, label=label)
                if crit is not None:
                    xc = crit.loc[port, f"x2pct_{method}_{regime}"]
                    if np.isfinite(xc):
                        yc = np.interp(xc, d.x, value(d))
                        ax.plot(xc * 100, yc, "o", ms=6, color=color, mec=SURF, mew=1.5, zorder=5)
                if mark_xd and method == "waterfall":
                    ax.axvline(crit.loc[port, "x_D"] * 100, color=color, lw=1, ls=(0, (2, 3)), alpha=0.8)
            if hline is not None:
                ax.axhline(hline, color=INK, lw=1, ls="--")
                ax.text(99, hline, "2% benchmark ", color=INK, fontsize=8, va="bottom", ha="right",
                        bbox=dict(fc=SURF, ec="none", pad=1))
            ax.set_title(f"{METHOD_LABEL[method]} - {REGIME_LABEL[regime]}", loc="left")
            ax.set_xlim(0, 100)
            ax.set_ylim(bottom=0)
            if i == 1:
                ax.set_xlabel("Redemption rate x (% of AUM)")
            if j == 0:
                ax.set_ylabel(ylabel)
    h, lab = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 0.985))
    fig.suptitle(title, x=0.01, ha="left", y=1.035, fontsize=12.5, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    footnote(fig, note)
    return fig


def main():
    os.makedirs(FIG, exist_ok=True)
    curves = pd.read_csv(os.path.join(TAB, "loss_curves.csv"))
    crit = pd.read_csv(os.path.join(TAB, "critical_metrics.csv")).set_index("portfolio")
    aum = 500e6

    fig = grid_2x2(curves, lambda d: d.L / aum * 100, r"$L(x) = R + M$  (% of AUM)",
                   "Liquidation loss curves",
                   "AUM = USD 500M, p = 0.5. Dotted verticals: liquidity depletion threshold $x_D$ "
                   "(Waterfall). Dots: 2% benchmark crossing $x^*_{2\\%}$.",
                   crit=crit, mark_xd=True)
    save(fig, "fig1_loss_curves.png")

    fig = grid_2x2(curves, lambda d: d.rho * 100, r"$\rho(x) = R\,/\,(x \cdot AUM)$  (%)",
                   "Liquidation-cost rate vs the 2% benchmark",
                   "$\\rho(x)$ includes market impact, so the 2% line (Rule 22c-1 swing-factor ceiling) is a "
                   "comparison benchmark, not a compliance test. Dots: $x^*_{2\\%}$.",
                   hline=2.0, crit=crit)
    save(fig, "fig2_cost_rate_vs_benchmark.png")

    fig = grid_2x2(curves, lambda d: d.E * 100, r"$E(x)$  (% of AUM)",
                   "Cost above the 2% benchmark, E(x)",
                   "E(x) = max(0, R(x) - 0.02 * x * AUM) / AUM (pre-redemption AUM). Interpretive metric "
                   "derived from R; not part of the loss function. Dots: onset at $x^*_{2\\%}$.",
                   crit=crit)
    save(fig, "fig3_excess_cost.png")

    # p-sensitivity
    ps = pd.read_csv(os.path.join(TAB, "p_sensitivity.csv"))
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.6), sharex=True)
    for i, method in enumerate(["waterfall", "pro_rata"]):
        for j, port in enumerate(PORT):
            ax = axes[i, j]
            for k, p in enumerate(sorted(ps.p.unique())):
                d = ps[(ps.method == method) & (ps.portfolio == port) & (ps.p == p)]
                ax.plot(d.x * 100, d.L / aum * 100, color=P_COLORS[k], lw=1.8,
                        label=f"p = {p:g}" + (" (baseline)" if p == 0.5 else ""))
            ax.set_title(f"{PORT[port][0].split(' (')[0]} - {METHOD_LABEL[method].split(' (')[0]}", loc="left")
            ax.set_xlim(0, 100)
            ax.set_ylim(bottom=0)
            if i == 1:
                ax.set_xlabel("Redemption rate x (%)")
            if j == 0:
                ax.set_ylabel("L(x) (% of AUM)")
    h, lab = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 0.985))
    fig.suptitle("p-sensitivity of L(x) = R + p * I * (H - Q)  (normal regime)", x=0.01, ha="left",
                 y=1.035, fontsize=12.5, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    footnote(fig, "p only scales M, so curves meet wherever no holding is partly sold: at Waterfall "
                  "depletion points and at x = 100%. R and $x^*_{2\\%}$ do not depend on p.")
    save(fig, "fig4_p_sensitivity.png")

    # Monte Carlo 90% range
    hl = pd.read_csv(os.path.join(TAB, "headline_losses.csv")).set_index("portfolio")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.6))
    for ax, (pre, det, title) in zip(axes, [
            ("waterfall", "waterfall_L", r"Waterfall: loss at $x_D$ (A 50% / B 60% / C 75%)"),
            ("prorata", "prorata_L_peak", "Pro-rata: peak loss (x = 100%)")]):
        for y, port in enumerate(reversed(list(PORT))):
            label, color = PORT[port]
            p5, p50, p95 = (hl.loc[port, f"{pre}_mc_{q}"] / 1e6 for q in ("p5", "p50", "p95"))
            ax.plot([p5, p95], [y, y], color=color, lw=9, alpha=0.35, solid_capstyle="round")
            ax.plot(p50, y, "o", color=color, ms=8, mec=SURF, mew=1.5)
            ax.plot([hl.loc[port, det] / 1e6] * 2, [y - 0.28, y + 0.28], color=INK, lw=1.6)
            ax.text(p95, y + 0.3, f" p5 {p5:.2f} | p50 {p50:.2f} | p95 {p95:.2f}", fontsize=7.8,
                    color=INK2, ha="right", va="bottom")
        ax.set_yticks(range(3))
        ax.set_yticklabels([PORT[p][0].split(" (")[0] for p in reversed(list(PORT))])
        ax.set_xlabel("Loss (USD millions)")
        ax.set_title(title, loc="left")
        ax.set_ylim(-0.6, 2.8)
        ax.set_xlim(left=0)
        ax.grid(axis="y", visible=False)
    fig.suptitle("Monte Carlo 90% range (fixed-g, normal regime)", x=0.01, ha="left", y=1.04,
                 fontsize=12.5, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    footnote(fig, "Band = p5-p95 of 1,000 bootstrap days, dot = p50, black tick = deterministic result. "
                  "Not a confidence interval and not VaR. AUM USD 500M, R + M.")
    save(fig, "fig5_monte_carlo_range.png")


if __name__ == "__main__":
    main()
