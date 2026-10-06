"""Regression tests for the tax engine. Expected values are worked out by hand in the comments (slab by slab),
NOT copied from the engine's own output. Source rules: see docs/TAX_RULES.md. Decision support, not tax advice."""
import pytest

from app.regime_engine import (CAPS, cap_deductions, compare, new_regime_tax as N, old_regime_tax as O, slab_tax)

FY = 2026  # FY2026-27 uses the FY2025-26 slab set (secondary sources report no change)


@pytest.mark.parametrize("gross,salaried,expected", [
    (1_275_000, True, 0),        # taxable 12.0L: slabs 0+20k+40k=60k, rebate 60k -> 0
    (1_300_000, True, 26_000),   # taxable 12.25L: slab 63,750; marginal relief -> tax = 25,000; +4% cess
    (1_500_000, True, 97_500),   # taxable 14.25L: 60k + 2.25L*15% = 93,750; *1.04
    (2_500_000, True, 319_800),  # taxable 24.25L: 300k + 25k*30% = 307,500; *1.04
    (1_200_000, False, 0),       # self-employed, no standard deduction: taxable 12L -> rebate
    (1_250_000, False, 52_000),  # taxable 12.5L: slab 67,500; relief caps at 50,000; *1.04
    (400_000, False, 0),
    (0, True, 0),
])
def test_new_regime(gross, salaried, expected):
    assert N(gross, FY, salaried)["total_tax"] == pytest.approx(expected, abs=1)


@pytest.mark.parametrize("gross,ded,age,expected", [
    (1_000_000, {"80C": 150_000}, 30, 75_400),   # taxable 8L: 12.5k + 3L*20% = 72,500; *1.04
    (400_000, {}, 30, 0),                         # taxable 3.5L: 5k < 12.5k rebate
    (560_000, {}, 30, 15_080),                    # taxable 5.1L: 12.5k + 0.1L*20% = 14.5k; no rebate (>5L); *1.04
    (600_000, {}, 65, 20_800),                    # senior, taxable 5.5L: 3-5L @5% = 10k; 0.5L @20% = 10k; *1.04
    (600_000, {}, 82, 10_400),                    # super senior, taxable 5.5L: 0.5L @20% = 10k; *1.04
    (1_000_000, {"80C": 300_000}, 30, 75_400),    # 80C capped at 1.5L, so same as the first case
])
def test_old_regime(gross, ded, age, expected):
    assert O(gross, ded, age, FY)["total_tax"] == pytest.approx(expected, abs=1)


def test_surcharge_marginal_relief_new_regime():
    # taxable 50.25L: slab 1,087,500; 10% surcharge would give 1,196,250, but relief caps tax at
    # 1,080,000 (tax at 50L) + 25,000 (income above 50L) = 1,105,000; *1.04 = 1,149,200
    assert N(5_025_000, FY, False)["total_tax"] == pytest.approx(1_149_200, abs=1)
    # exactly 50L: no surcharge. slab 1,080,000 * 1.04
    assert N(5_000_000, FY, False)["total_tax"] == pytest.approx(1_123_200, abs=1)


def test_surcharge_full_new_and_old():
    # new, taxable 60L: slab 1,380,000; +10% = 1,518,000; no relief; *1.04
    assert N(6_000_000, FY, False)["total_tax"] == pytest.approx(1_578_720, abs=1)
    # old, taxable 1.2Cr: slab 3,412,500; +15% = 3,924,375; no relief; *1.04
    assert O(12_000_000, {}, 30, FY, False)["total_tax"] == pytest.approx(4_081_350, abs=1)


def test_new_regime_surcharge_capped_at_25pct_old_goes_to_37():
    new = N(100_000_000, FY, False)   # 10 Cr
    old = O(100_000_000, {}, 30, FY, False)
    assert new["surcharge"] / new["slab_tax"] == pytest.approx(0.25, abs=0.001)
    assert old["surcharge"] / old["slab_tax"] == pytest.approx(0.37, abs=0.001)


def test_deduction_caps():
    c = cap_deductions({"80C": 400_000, "80CCD1B": 90_000, "80D": 60_000, "24b": 500_000}, 30)
    assert c == {"80C": 150_000, "80CCD1B": 50_000, "80D": 25_000, "24b": 200_000}
    assert cap_deductions({"80D": 60_000}, 65)["80D"] == 50_000
    assert cap_deductions({"other": 123_456}, 30)["other"] == 123_456  # user-computed HRA etc. passes through


def _scan(fn, cliff_ok=()):
    """Walk income upward; return the incomes where tax jumped by more than the extra income (+4% cess)."""
    cliffs, prev, x = [], 0.0, 0.0
    while x <= 60_000_000:
        step = 10_000 if x < 15_000_000 else 250_000
        t = fn(x)
        assert t + 1e-6 >= prev, f"tax fell at income {x}"
        if t - prev > step * 1.04 + 1e-6:
            cliffs.append(x)
        prev, x = t, x + step
    return cliffs


def test_new_regime_has_no_cliffs():
    """Higher income never lowers tax and no extra rupee costs more than a rupee of tax (+cess). That is what
    87A marginal relief and surcharge marginal relief guarantee in the new regime."""
    assert _scan(lambda x: N(x, FY, False)["total_tax"]) == []


def test_old_regime_has_exactly_one_cliff_at_5_lakh():
    """The old-regime 87A rebate has NO marginal relief in the law: just above Rs 5,00,000 taxable income the
    Rs 12,500 rebate disappears. The property scan found this; the engine is right and the test documents it."""
    cliffs = _scan(lambda x: O(x, {}, 30, FY, False)["total_tax"])
    assert cliffs == [510_000.0]  # first scanned income above the Rs 5,00,000 threshold


def test_compare_picks_cheaper_regime_and_reports_caveat():
    r = compare(1_500_000, {"80C": 150_000, "80D": 25_000}, 30, FY, True)
    assert r["recommended"] == "new" and r["best_tax"] == r["new"]["total_tax"]
    assert "not tax advice" in r["note"].lower()
    assert r["rules_meta"]["last_verified"]


def test_old_regime_wins_with_large_other_deductions():
    # 20L salaried with 5L of HRA/other + all standard caps: old regime is cheaper
    r = compare(2_000_000, {"80C": 150_000, "80CCD1B": 50_000, "80D": 25_000, "24b": 200_000, "other": 500_000}, 30, FY, True)
    assert r["recommended"] == "old"


def test_slab_tax_edges():
    slabs = [(100, 0.0), (200, 0.10), (float("inf"), 0.2)]
    assert slab_tax(100, slabs) == 0 and slab_tax(150, slabs) == 5 and slab_tax(300, slabs) == 10 + 20
