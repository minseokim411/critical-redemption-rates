"""
Regression and invariant tests.

Reference values were produced by the team's final (spread-corrected) model
script before it was refactored into this package. The refactor must
reproduce them exactly.

    python -m pytest -q
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from crr import config as C            # noqa: E402
from crr import model as M             # noqa: E402
from crr import uncertainty as U       # noqa: E402
from crr.agg_target import derive_agg_target  # noqa: E402

AUM = C.TOTAL_AUM


@pytest.fixture(scope="module")
def data():
    n = M.load_metrics_csv(os.path.join(ROOT, "data", "liquidity_metrics_normal.csv"))
    s = M.load_metrics_csv(os.path.join(ROOT, "data", "liquidity_metrics_stress_2020.csv"))
    params = {k: M.build_asset_params(list(w), n, s) for k, w in C.PORTFOLIOS.items()}
    return n, s, params


# x_D, x*2% (waterfall normal/stress, pro-rata normal/stress), L at x_D, pro-rata peak L
REFERENCE = {
    "A_aggressive":   (0.50, 0.573, 0.148, 0.0795, 0.0065, 3_967_535.687, 32_920_915.490),
    "B_moderate":     (0.60, 0.663, 0.148, 0.1490, 0.0160, 5_211_967.813, 24_732_305.763),
    "C_conservative": (0.75, 0.783, 0.148, 0.2920, 0.0450, 7_278_546.399, 18_150_115.044),
}
REFERENCE_MC = {   # (waterfall p5, p50, p95, pro-rata p5, p50, p95), USD
    "A_aggressive":   (2_234_145.0, 3_709_802.4, 6_102_910.6, 18_656_621.4, 30_609_563.5, 52_440_489.3),
    "B_moderate":     (2_933_366.5, 4_873_168.6, 8_018_991.1, 13_655_070.4, 23_123_496.4, 40_364_173.4),
    "C_conservative": (4_094_104.3, 6_805_060.2, 11_201_480.7, 10_363_120.8, 17_404_283.3, 29_581_591.9),
}


@pytest.mark.parametrize("name", list(C.PORTFOLIOS))
def test_reference_headlines(data, name):
    _, _, params = data
    w, ap = C.PORTFOLIOS[name], data[2][name]
    x_d, wn, ws, pn, ps, l_w, l_p = REFERENCE[name]
    assert M.liquidity_depletion_threshold(w) == pytest.approx(x_d)
    assert M.benchmark_crossing(ap, w, AUM, "waterfall", "normal") == pytest.approx(wn)
    assert M.benchmark_crossing(ap, w, AUM, "waterfall", "stress") == pytest.approx(ws)
    assert M.benchmark_crossing(ap, w, AUM, "pro_rata", "normal") == pytest.approx(pn)
    assert M.benchmark_crossing(ap, w, AUM, "pro_rata", "stress") == pytest.approx(ps)
    r, m = M.compute_R_M(ap, w, x_d, AUM, "waterfall", "normal")
    assert r + m == pytest.approx(l_w, abs=0.01)
    R, Mm = M.compute_loss_curve(ap, w, AUM, "pro_rata", "normal")
    assert (R + Mm).max() == pytest.approx(l_p, abs=0.01)


@pytest.mark.parametrize("name", list(C.PORTFOLIOS))
def test_reference_monte_carlo(data, name):
    n, _, params = data
    w, ap = C.PORTFOLIOS[name], params[name]
    x_d = M.liquidity_depletion_threshold(w)
    mw = U.mc_loss_at_rate(ap, n, w, AUM, "waterfall", x_d)
    mp = U.mc_peak_loss(ap, n, w, AUM, "pro_rata")
    got = (mw["p5"], mw["p50"], mw["p95"], mp["p5"], mp["p50"], mp["p95"])
    for g, ref in zip(got, REFERENCE_MC[name]):
        assert g == pytest.approx(ref, abs=1.0)


def test_corrected_stress_spreads():
    """The published version must use the corrected Kargar-based stress spreads."""
    assert C.SPREADS["LQD"]["stress"] == 0.0259
    assert C.SPREADS["HYG"]["stress"] == 0.0383


def test_sigma_adv_cancel_in_deterministic_impact(data):
    """With g calibrated to T, impact = T*sqrt(Q/Q_ref) for any sigma/ADV."""
    _, _, params = data
    ap = params["A_aggressive"]
    for t, a in ap.items():
        for reg in M.REGIMES:
            q = 37_000_000.0
            impact = a[f"g_{reg}"] * a[f"sigma_{reg}"] * np.sqrt(q / a[f"adv_{reg}"])
            assert impact == pytest.approx(a[f"target_{reg}"] * np.sqrt(q / C.Q_REF), rel=1e-12)


def test_order_magnitudes_do_not_matter(data):
    _, _, params = data
    w, ap = C.PORTFOLIOS["A_aggressive"], params["A_aggressive"]
    base = M.compute_loss_curve(ap, w, AUM, "waterfall")
    for hw in ({"AGG": 0.51, "LQD": 0.50, "HYG": 0.49}, {"AGG": 0.99, "LQD": 0.02, "HYG": 0.01}):
        order = sorted(hw, key=lambda t: -hw[t])
        other = M.compute_loss_curve(ap, w, AUM, "waterfall", order=order)
        np.testing.assert_array_equal(base[0], other[0])
        np.testing.assert_array_equal(base[1], other[1])


def test_p_only_moves_M(data):
    _, _, params = data
    w, ap = C.PORTFOLIOS["B_moderate"], params["B_moderate"]
    R0, _ = M.compute_loss_curve(ap, w, AUM, "pro_rata", p=0.0)
    R1, _ = M.compute_loss_curve(ap, w, AUM, "pro_rata", p=1.0)
    np.testing.assert_array_equal(R0, R1)


def test_excess_cost_zero_before_crossing(data):
    _, _, params = data
    for name, w in C.PORTFOLIOS.items():
        ap = params[name]
        for method in M.METHODS:
            x2 = M.benchmark_crossing(ap, w, AUM, method, "normal")
            E = M.excess_cost_curve(ap, w, AUM, method, "normal")
            assert np.all(E[C.X_GRID < x2 - 1e-9] == 0.0)


def test_agg_bottom_up_matches_adopted_constant():
    _, _, totals = derive_agg_target()
    assert round(totals["normal"] * 100, 4) == round(C.AGG_TARGET_NORMAL * 100, 4)
    assert round(totals["stress"] * 100, 4) == round(C.AGG_TARGET_STRESS * 100, 4)


def test_readme_results_block_in_sync():
    """README results block must equal the generator output (code -> README)."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import make_summary
    text = open(os.path.join(ROOT, "README.md")).read()
    i = text.index(make_summary.START) + len(make_summary.START)
    j = text.index(make_summary.END)
    assert text[i:j].strip() == make_summary.build(include_supplementary=False).strip()
