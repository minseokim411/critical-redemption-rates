"""
Model assumptions: the single source of truth for every input.

Every number in this file is an *assumption*: a literature value, a value derived
from one, or a team modelling choice. Each one says where it comes from. Nothing
here is estimated from the ETF data in `data/`. Those files only feed the
Monte Carlo range (see `uncertainty.py`).

Units
-----
* Rates and percentages are decimals: 0.0075 means 0.75 %.
* Money is in USD.
* Target impacts T are "% price impact per USD 1 million sold" (Q_ref = USD 1M).
* Spreads are FULL bid-ask spreads. The model charges s/2 per dollar sold.
"""

import numpy as np

# ---------------------------------------------------------------------------
# 1. Fund and portfolios
# ---------------------------------------------------------------------------
# The research object is a HYPOTHETICAL open-end (mutual) bond fund that pays
# redemptions in cash at NAV and may sell holdings to do so. AGG, LQD and HYG
# are used only as ASSET-CLASS PROXIES:
#   AGG -> broad U.S. investment-grade aggregate bonds (not "Treasuries": per
#          the iShares fact sheet it is ~47% Treasury, ~23% agency MBS, ~25% IG
#          corporate, ~6% other),
#   LQD -> U.S. investment-grade corporate bonds,
#   HYG -> U.S. high-yield corporate bonds.
# The ETFs themselves are NOT the object of study. ETF shares are redeemed
# in kind through authorised participants, and Rule 22c-1 swing pricing does
# not apply to ETFs.

TOTAL_AUM = 500_000_000                                # baseline fund size (USD)
AUM_SENSITIVITY_LIST = [100_000_000, 500_000_000, 1_000_000_000]

# HY share stepped 20% -> 10% -> 0%. 20% follows the high-yield cap commonly
# allowed by "Core-Plus" bond funds. 0% mirrors a traditional "Core" bond fund.
PORTFOLIOS = {
    "A_aggressive":   {"AGG": 0.50, "LQD": 0.30, "HYG": 0.20},
    "B_moderate":     {"AGG": 0.60, "LQD": 0.30, "HYG": 0.10},
    "C_conservative": {"AGG": 0.75, "LQD": 0.25},
}

# Waterfall selling order. Only the ORDER of these weights is used. They mirror
# the direction of the Basel III LCR HQLA hierarchy (Level 1 > Level 2A >
# non-HQLA). The magnitudes are arbitrary team choices and do not enter any
# loss calculation; `scripts/run_model.py` checks this invariance explicitly.
HQLA_WEIGHTS = {"AGG": 0.90, "LQD": 0.65, "HYG": 0.35}
LIQUIDITY_ORDER = sorted(HQLA_WEIGHTS, key=lambda t: -HQLA_WEIGHTS[t])  # AGG, LQD, HYG

# ---------------------------------------------------------------------------
# 2. Target impact T_i  (price impact of selling Q_ref = USD 1M, in %)
# ---------------------------------------------------------------------------
Q_REF = 1_000_000

# LQD - Ellul, Jotikasthira & Lundblad (2011, JFE), Section 4.2 / Table 8:
#   "The price impact of insurance companies' selling is twice as large in
#    2001-2002 (ranging from 1.1% to 1.9%) as in 2003-2004 (0.6% to 0.9%)."
# Normal = midpoint of 0.6-0.9%. Stress = 1.6%, which lies inside the
# 1.1-1.9% range; the exact point estimate is not confirmed (see limitations).
# Calling 2003-04 "normal" and 2001-02 "stress" is the team's mapping.
LQD_TARGET_NORMAL = 0.0075
LQD_TARGET_STRESS = 0.016

# AGG - bottom-up composite of its components (see `agg_target.py`):
#   T_AGG = sum_k w_k^1.5 * T_k
# Rounded values adopted by the team; `agg_target.py` re-derives them.
AGG_TARGET_NORMAL = 0.000996        # 0.0996 %
AGG_TARGET_STRESS = 0.002271        # 0.2271 %

# HYG normal - LQD normal scaled by relative market depth:
#   sqrt(IG ADV / HY ADV) = sqrt(36 / 10) = 1.897 (Coalition Greenwich, 2024
#   U.S. corporate bond ADV: IG USD 36bn, HY USD 10bn). 0.75% x 1.897 = 1.42%.
HYG_TARGET_NORMAL = 0.0142

# HYG stress - no HY-specific normal->stress multiple was found, so two
# competing multiples bracket the value: 2.13x (Ellul IG stress/normal) and
# 3.4x (HY liquidity-premium multiple used in the team's spread derivation).
# Five evenly spaced values, linspace(2.13, 3.4, 5) x 1.42%. The middle value
# (3.926%) is the representative input; all five feed the stress-assumption
# sensitivity range.
HYG_TARGET_STRESS_SENSITIVITY = [0.03025, 0.03475, 0.03926, 0.04377, 0.04828]
# AGG keeps the same 5-slot structure, but all slots hold the single bottom-up
# point estimate. It is NOT a range, so AGG adds no width to that sensitivity.
AGG_TARGET_STRESS_SENSITIVITY = [AGG_TARGET_STRESS] * 5
STRESS_REPRESENTATIVE_IDX = 2

# ---------------------------------------------------------------------------
# 3. Full bid-ask spreads s_i
# ---------------------------------------------------------------------------
# Units differ by source, so each source is converted to a FULL spread:
#   Fleming (2003): quoted inter-dealer bid-ask (already full).
#   Harris (2015): EFFECTIVE HALF-spreads, IG USD 1-5MM 31.2bp, non-IG 1MM+
#       50.7bp -> x2. These are bucket-level proxies for each asset class,
#       not estimates for the LQD/HYG holdings.
#   Kargar et al. (2021): risky-principal cost defined as
#       2Q(P_trade - P_ref)/P_ref, which already contains the factor 2
#       -> used as is (NO extra x2).
#   AGG stress: midpoint of the 0.049%-0.146% range (Liberty Street Economics, 2020).
#   HYG stress: median of 1.014% x [3.4, LQD stress/normal = 2.59/0.624 = 4.15]
#       = median of [3.45%, 4.21%] = 3.83%.
# Correction history: an earlier version doubled the Kargar figure a second
# time (LQD stress 5.18%, HYG stress 5.935%). That double conversion is
# removed here, and all published outputs use the corrected values below.
SPREADS = {
    "AGG": {"normal": 0.000244, "stress": 0.000975},
    "LQD": {"normal": 0.00624,  "stress": 0.0259},
    "HYG": {"normal": 0.01014,  "stress": 0.0383},
}

# ---------------------------------------------------------------------------
# 4. Permanent share of impact, p  (used only in M)
# ---------------------------------------------------------------------------
# M_i = p * I_i * (H_i - Q_i). Baseline p = 0.5 follows the roughly 1:1
# permanent vs temporary split in Almgren, Thum, Hauptmann & Li (2005). That
# study is an EQUITY study, and bond evidence points both ways, so p is
# treated as a sensitivity parameter (P_GRID).
PERMANENT_IMPACT_FRAC = 0.5
P_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]

# ---------------------------------------------------------------------------
# 5. 2 % swing-cost benchmark
# ---------------------------------------------------------------------------
# SEC Rule 22c-1(a)(3) caps a swing factor at 2% of NAV per share. Swing
# pricing is optional, excludes money-market funds and ETFs, and its swing
# factor may reflect spread costs, transaction fees/charges and
# borrowing-related costs. Market impact is NOT included. Our cost R includes
# market impact, so 2% is used ONLY as a comparison BENCHMARK for the
# liquidation-cost rate rho(x) = R(x)/(x*AUM). It is NOT a regulatory
# compliance test.
BENCHMARK_2PCT = 0.02

# ---------------------------------------------------------------------------
# 6. Grids and Monte Carlo settings
# ---------------------------------------------------------------------------
X_GRID = np.arange(0.0, 1.001, 0.005)          # curves: 0-100% in 0.5 pp steps
X_GRID_FINE = np.arange(0.0, 1.0005, 0.0005)   # benchmark crossing: 0.05 pp steps
N_MC_ITER = 1000
RNG_SEED = 42

# Historical redemption reference points. These are recorded with the
# model, but they are not part of any headline result.
REDEMPTION_BENCHMARKS = {
    "Bouveret_1st_pct_low": 0.09,
    "Bouveret_1st_pct_high": 0.19,
    "Falato_COVID_monthly_peak": 0.10,
    "Falato_COVID_daily_peak": 0.01,
    "Falato_TaperTantrum_2013": 0.022,
}
