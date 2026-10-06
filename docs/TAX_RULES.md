# Tax rules used and how they were checked

Decision support, not tax or investment advice. Rules live in `backend/app/regime_engine.py`; provenance is in `RULES_META` (also shown by `GET /system`).

| Item | Value in code | Checked against |
|---|---|---|
| New regime slabs FY2025-26 / 2026-27 | 0-4L nil, 4-8L 5%, 8-12L 10%, 12-16L 15%, 16-20L 20%, 20-24L 25%, >24L 30% | Secondary sources (ClearTax, news). **FY2026-27 is assumed unchanged; verify.** |
| 87A rebate (new) | up to Rs 60,000 if taxable <= 12L, with marginal relief just above | Secondary sources |
| 87A rebate (old) | up to Rs 12,500 if taxable <= 5L, **no marginal relief** (hard cliff) | Secondary sources; behaviour covered by a property test |
| Standard deduction | 75,000 new / 50,000 old, salaried only | Secondary sources |
| Surcharge | 10/15/25% (new, capped at 25%), up to 37% (old), with marginal relief | Secondary sources |
| Cess | 4% | - |
| Caps | 80C 1.5L, 80CCD(1B) 50k, 80D 25k (50k senior), 24(b) 2L | Long-standing; Income-tax Act 2025 renumbers sections (80C -> s.123 etc.) |
| Advance tax | 15% Jun 15, 45% Sep 15, 75% Dec 15, 100% Mar 15; none if liability after TDS < Rs 10,000; resident seniors without business income exempt | incometaxindia.gov.in advance-tax page |
| 44ADA | single March instalment, 50% presumptive income | **Not independently verified here.** Eligibility limits and conditions are not modelled. Confirm with a professional. |

Not supported (the app says so on screen): capital gains and ELSS gains tax, HRA/LTA (enter your computed total in Profile -> "Other old-regime deductions"),
employer NPS, 80D for parents, carried-forward losses, NRIs/HUFs/companies, interest under 234A/B/C, TDS credit detail.

Tests: `backend/tests/test_tax_engine.py` (23 tests: slab boundaries, rebate cliffs and marginal relief, surcharge continuity, monotonicity, regime comparison).
Before relying on any number for a real filing, re-check it against the Finance Act text or incometax.gov.in.
