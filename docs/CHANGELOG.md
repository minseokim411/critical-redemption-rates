# Methodology change log

This file records the main specification changes made before publication. Each change was re-run end to end. The economic assumptions were left untouched unless an entry says otherwise.

| Date | Change | Effect on results |
|---|---|---|
| 2026-09-18 | Portfolios rebuilt as a pure bond credit spectrum: AGG/LQD/HYG, with HY share 20% / 10% / 0%. The equity sleeve was dropped. | New baseline |
| 2026-09-29 | Stress σ/ADV taken from one actual day (joint illiquidity rank) instead of independent percentiles. | None on deterministic results (σ/ADV cancel) |
| 2026-09 | Permanent-impact share p = 0.5 applied to M only. The earlier version used the full impact on unsold holdings. The curvature-based threshold was replaced by the structural depletion threshold x_D. | M and L curves |
| 2026-09-30 | AGG target impact rebuilt bottom-up from its components: normal 0.149% → 0.0996%, stress 0.82% → 0.2271%. AGG relabelled "broad IG aggregate", not "Treasury". | All AGG-dependent results |
| 2026-09-30 | 2% benchmark crossing x\*₂% added for both liquidation rules. | New metric |
| 2026-10-01 | Denominator of the cost rate corrected from AUM to the redeemed amount x·AUM, i.e. cost per redeemed dollar. E(x), the cost above the benchmark, added. | x\*₂% |
| 2026-10-03 | Data rebuilt with a rolling-window lead-in, so measures are valid from day one, and with fixed end dates. A 0.05 pp crossing grid was added. | Monte Carlo range moved 1–4%; deterministic results unchanged |
| 2026-10-05 | **Stress spread unit correction.** Kargar et al. (2021) risky-principal cost already includes the factor 2, so the extra ×2 was removed: LQD stress 5.18% → 2.59%, HYG stress 5.935% → 3.83%. Normal spreads (Harris effective half-spread × 2) were unchanged. | Stress Pro-rata x\*₂%, stress E(x) and the stress-assumption range. Normal results, x_D and the Waterfall stress crossing (14.80%) unchanged. |
| 2026-10 | Code refactored into the `crr` package for publication. Numerically identical to the final team script; checked by `tests/test_model.py`. Terminology aligned: "SEC cap" → "2% swing-cost benchmark", "swing factor" → "liquidation-cost rate ρ(x)", "MC CI" → "Monte Carlo 90% range". | None |
