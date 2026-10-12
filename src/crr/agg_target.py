"""
Bottom-up target impact for AGG.

Why bottom-up
-------------
AGG is a broad aggregate bond fund, not a Treasury fund. Treating it as one
asset hides the fact that its cost of liquidity comes almost entirely from
its corporate sleeve. The model therefore builds T_AGG from its components.

Derivation (same square-root law as the rest of the model)
-----------------------------------------------------------
Selling Q of AGG pro rata means selling Q_k = w_k * Q of each component k.

    I_k(Q_k)  = T_k * sqrt(Q_k / Q_ref)
    Cost_k    = I_k(Q_k) * Q_k = T_k * w_k^1.5 * Q * sqrt(Q / Q_ref)
    sum_k Cost_k = (sum_k w_k^1.5 * T_k) * Q * sqrt(Q / Q_ref)

Matching this to a single-asset AGG cost, T_AGG * Q * sqrt(Q / Q_ref), gives

    T_AGG = sum_k w_k^1.5 * T_k

The match assumes:
  * components are sold pro rata at the same time;
  * component impacts are independent of each other;
  * spreads are handled separately (they enter R through s/2, not T).

Because w^1.5 is not additive, how components are bucketed matters. Each
bucket below is therefore computed separately.

Component inputs (normal regime, % impact per USD 1M)
-----------------------------------------------------
Treasury-like (Treasury, sovereign, supranational): 0.00078%. A USD 100M order
    moves the 5-year note by 2/256 of a point (NY Fed Liberty Street
    Economics), scaled to USD 1M with sqrt(Q).
Agency MBS: 0.0375%. Half of a 5-10bp TBA bid-ask spread is used as a proxy
    for small-trade impact. This is a conceptual approximation, because a
    spread is not the same as impact.
Corporate-like (IG corporate, CMBS, local authority, unclassified residual):
    0.75%, the same Ellul et al. (2011) value used for LQD.
Cash: 0%.

Stress: Treasury-like and MBS use 5.5x (midpoint of the 5-6x Treasury
multiple, Fleming & Ruela 2020). MBS borrows the Treasury multiple because no
MBS-specific multiple was found. Corporate-like uses the 1.6% Ellul stress
value.

Weights: iShares AGG fact sheet (as of 2026-06-30).

Known data issue (unresolved)
-----------------------------
The "Other" bucket is 5.66% of AGG, but its listed sub-items add up to 5.60%.
The 0.06 pp gap is left unallocated here. If it belongs to a corporate-like
item, T_AGG(normal) rounds to 0.0997% instead of 0.0996%. The model keeps the
team-adopted rounded constants in `config.py` until this is resolved.
"""

import pandas as pd

from . import config as C

T_TREASURY = 0.0000078   # 0.00078 %
T_MBS = 0.000375         # 0.0375 %
T_CORP = C.LQD_TARGET_NORMAL
TREASURY_STRESS_MULT = 5.5

# (component, sleeve, weight, mapping)
AGG_COMPONENTS = [
    ("Treasury",        "Treasury",    0.4665, "treasury"),
    ("Agency MBS",      "Agency MBS",  0.2281, "mbs"),
    ("IG Corporate",    "IG Corporate", 0.2488, "corp"),
    ("Sovereign",       "Other",       0.0109, "treasury"),
    ("Supranational",   "Other",       0.0092, "treasury"),
    ("CMBS",            "Other",       0.0139, "corp"),
    ("Local Authority", "Other",       0.0058, "corp"),
    ("Residual",        "Other",       0.0091, "corp"),
    ("Cash",            "Other",       0.0071, "cash"),
]
OTHER_REPORTED_WEIGHT = 0.0566


def component_targets(regime):
    """Per-component target impact T_k for the given regime."""
    if regime == "normal":
        return {"treasury": T_TREASURY, "mbs": T_MBS, "corp": T_CORP, "cash": 0.0}
    return {
        "treasury": T_TREASURY * TREASURY_STRESS_MULT,
        "mbs": T_MBS * TREASURY_STRESS_MULT,
        "corp": C.LQD_TARGET_STRESS,
        "cash": 0.0,
    }


def derive_agg_target():
    """Return (component table, sleeve summary, {regime: T_AGG})."""
    rows = []
    totals = {}
    for regime in ("normal", "stress"):
        tk = component_targets(regime)
        for name, sleeve, w, mapping in AGG_COMPONENTS:
            rows.append({
                "regime": regime, "component": name, "sleeve": sleeve,
                "weight": w, "mapping": mapping, "T_k": tk[mapping],
                "w_k_1.5_times_T_k": w ** 1.5 * tk[mapping],
            })
    comp = pd.DataFrame(rows)
    for regime, g in comp.groupby("regime"):
        totals[regime] = g["w_k_1.5_times_T_k"].sum()
    comp["contribution_share"] = comp.apply(
        lambda r: r["w_k_1.5_times_T_k"] / totals[r["regime"]], axis=1)
    sleeve = (comp.groupby(["regime", "sleeve"], sort=False)
                  .agg(weight=("weight", "sum"),
                       contribution=("w_k_1.5_times_T_k", "sum"),
                       contribution_share=("contribution_share", "sum"))
                  .reset_index())
    return comp, sleeve, totals
