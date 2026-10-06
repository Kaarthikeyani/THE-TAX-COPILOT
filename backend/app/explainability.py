"""Local clause-citation lookup (stand-in for the Qdrant RAG layer)."""

NOTE = ("Citations refer to the Income-tax Act, 1961. The Income-tax Act, 2025 applies from 1 April 2026 and "
        "renumbers provisions - confirm the equivalent section before filing.")

CLAUSES = {
    "80C": {"title": "Section 80C - Life insurance, PPF, ELSS, tuition fees and similar",
            "limit": "Up to Rs 1,50,000 a year (combined with 80CCC and 80CCD(1))",
            "summary": "Deduction for life insurance premiums, PPF/EPF/VPF, ELSS mutual funds, 5-year tax-saver FDs, NSC, "
                       "children's tuition fees and principal repayment of a home loan. Available in the old regime only."},
    "80CCD1B": {"title": "Section 80CCD(1B) - Additional NPS contribution",
                "limit": "Additional Rs 50,000 over and above the 80C limit",
                "summary": "Contributions to the National Pension System (Tier I) qualify for a further deduction. Old regime only."},
    "80D": {"title": "Section 80D - Health insurance and preventive check-ups",
            "limit": "Rs 25,000 for self/family (Rs 50,000 if senior citizen); preventive check-up up to Rs 5,000 within the limit",
            "summary": "Premiums paid for health insurance and preventive health check-ups. Old regime only."},
    "24b": {"title": "Section 24(b) - Interest on housing loan",
            "limit": "Up to Rs 2,00,000 for a self-occupied property",
            "summary": "Interest (not principal) on a home loan is deductible from house-property income. Old regime only."},
    "80G": {"title": "Section 80G - Donations",
            "limit": "50% or 100% of the donation depending on the institution, subject to qualifying limits",
            "summary": "Donations to approved funds and charities. This planner counts 50% as a conservative default."},
    "87A": {"title": "Section 87A - Rebate for resident individuals",
            "limit": "New regime: up to Rs 60,000 (taxable income up to Rs 12 lakh) from FY2025-26; old regime: Rs 12,500 (up to Rs 5 lakh)",
            "summary": "Reduces tax to nil for taxable incomes up to the threshold, with marginal relief just above it."},
    "115BAC": {"title": "Section 115BAC - New tax regime",
               "limit": "Lower slab rates; most deductions not allowed (standard deduction for salaried is)",
               "summary": "The default regime. A taxpayer can opt out into the old regime (business-income earners with restrictions)."},
    "208": {"title": "Sections 207-211 and 234C - Advance tax",
            "limit": "Applies when tax payable is Rs 10,000 or more; due 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%) cumulative",
            "summary": "Self-employed taxpayers pay tax in instalments through the year; shortfalls attract interest under 234B/234C."},
    "none": {"title": "No specific deduction section",
             "limit": "-", "summary": "This transaction does not map to a tax deduction; it still counts toward cash-flow."},
}


def explain(section: str) -> dict:
    key = section if section in CLAUSES else "none"
    return {"section": section, **CLAUSES[key], "disclaimer": NOTE}
