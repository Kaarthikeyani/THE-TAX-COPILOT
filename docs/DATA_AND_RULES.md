# Teaching the app your merchants (no Python needed)

Order of decisions for each message: **your corrections/rules** -> `data/merchant_taxonomy.json` + `data/user_rules.csv` -> keyword fallback -> ML model -> "uncategorized".

| You want to | Do this |
|---|---|
| Fix one wrong category | Activity -> tap the transaction -> "Wrong category?" -> pick -> Save. Tick "apply to similar" to fix look-alike spellings and remember the merchant. |
| Add a merchant rule | Append a line to `backend/data/user_rules.csv` (`keyword,category`) or `python -m app.maintenance add-rule SWIGGY food_dining`; then POST `/model/retrain` or restart. |
| Add training examples | `data/training_examples.csv` (`text,category`) or `python -m app.maintenance add-example "AXIS LONG TERM EQUITY" elss_investment`, then "Refresh model" (Activity page). |
| See valid categories | `python -m app.maintenance categories` |
| Measure on real messages | Put labelled SMS in `data/real_labelled.csv` (template: `data/real_labelled_TEMPLATE.csv`), then `python experiments/evaluate_real.py`. Do not train on them first. |

Labelling guide: label by what the money was **for**. Money out to a mutual fund called "...Tax Saver / ELSS" is `elss_investment`; school fees are `tuition_fees`;
a transfer to a person you cannot identify is `uncategorized`. Money in uses income categories only (`salary_income`, `freelance_income`, `other_income`).
Refunds and reversals are `other_income`. When unsure use `uncategorized`; a wrong tax-section label costs more than a missing one.

Where the datasets are: `data/training_examples.csv` (shipped training strings), `data/synthetic/{train,val,test}.csv` (**synthetic**, written by the authors, used only for the experiments),
`data/merchant_taxonomy.json` (built-in rules), `data/user_rules.csv` (yours), the database `data/copilot.db` (your transactions, learned rules).
