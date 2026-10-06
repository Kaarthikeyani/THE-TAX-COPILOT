# Comparison with the base paper

Base paper: M. Suganya, A. Syed Ismail, R. Jayaraj, S. Ganesh Kumar, "GenAI-Powered Personal Finance Consultant: Integrating Machine
Learning and Generative AI for Personalized Financial Recommendations and Literacy Enhancement", ICDSBS 2025,
DOI 10.1109/ICDSBS63635.2025.11031897. Everything in the "Paper" column below is taken from that PDF. Nothing was re-run on their data
(the paper does not release it).

## Different problems, so no head-to-head number

| | Paper | This project |
|---|---|---|
| Task | Predict a user's monthly **savings** from a survey profile, then recommend an allocation | **Classify bank SMS** into 22 tax/spending categories, estimate tax (old vs new regime), plan monthly safe-to-invest |
| Input | Google-Form answers (age, income, expenses, savings...) typed by the user | Bank SMS (parsed: amount, debit/credit, merchant, date, balance) |
| Output | Allocation across emergency fund, insurance, shares, FDs; Llama 3.1 wording | Category, tax-saving flag, tax under both regimes, 12-month cash plan, advance-tax dates |
| ML type | Regression | Multi-class classification (+ deterministic tax engine) |

Because the target variable differs, the paper's R2 / MAE cannot be compared with our accuracy / F1. Do not put them in one table as if they were
the same measurement.

## What each reports

| Item | Paper | This project |
|---|---|---|
| Regression metrics | MAE 0.1008, MSE 0.0201, RMSE 0.1418, R2 0.4141 (normalised savings) | Not applicable (not a regression task) |
| Classification metrics | None | Accuracy, macro precision / recall / F1, MCC, kappa, top-3, log-loss, Brier, ECE, Wilson 95% CI (`experiments/results/summary.json`) |
| Headline claim | "85% alignment with financial experts" (GenAI) vs 78% (ML) vs 72% (rules) | Logistic regression on **synthetic** unseen merchants: acc 69.8%, macro P 72.8%, macro R 70.8%, F1 71.2% (11 other models listed) |
| Ground truth | Expert advice (number of experts, rubric, sample size not stated) | Labels from the generator; real-SMS labels are **not yet collected** |
| Dataset size / split | Not stated | 3,264 / 1,086 / 1,074 rows, 544 / 181 / 179 disjoint merchants, SHA-256 of each split |
| Confidence intervals / significance tests | None | Wilson CIs, McNemar vs selected model, ablations, learning curve |
| Calibration | None | ECE, reliability diagram |
| Generative AI | Llama 3.1 via Ollama (explanations); GAN for synthetic data (no GAN results shown) | Template explanations (`explainability.py`); no LLM yet; synthetic data from a rule-based generator, not a GAN |
| Latency | 1.2 s (GenAI) vs 0.9 s (ML) | ms per message per model in the Accuracy table |
| User study | 80% found explanations clear, 65% would consider AI planning (sample size not stated) | None yet |
| Real data | Google-Form responses | None yet; `evaluate_real.py` and `real_labelled_TEMPLATE.csv` are ready |
| Tax | Not covered | Old/new regime, rebate, surcharge, cess, advance tax (23 tests; FY26-27 slabs from secondary sources) |
| Interface | Streamlit web app | FastAPI + web app; **no mobile app yet** |
| Security | Future scope | Field-level encryption, token auth, rate limiting, consent log (single user, no TLS) |

## Where this project is stronger

* Reproducible, leakage-controlled evaluation (merchant-disjoint splits, fixed seed, hashes).
* Many more metrics, uncertainty reported, 12 models compared, calibration measured.
* Actionable Indian tax logic and month-by-month cash planning, which the paper does not attempt.
* Automatic input (SMS) instead of a manual survey form.

## Where the paper is stronger (be honest in the report)

* It used **real human data** and a **user study**; we have neither yet.
* It has a **generative explanation layer** (Llama 3.1) and a chatbot; ours is template text.
* It addresses recommendation across asset classes (FDs, shares, insurance) and savings prediction.
* It is a published, peer-reviewed venue; our numbers are not.

## Weaknesses of the paper to cite carefully

* The 85 / 78 / 72% figures have no stated sample size, expert count, rubric or interval, so the 7-13 point gaps cannot be judged.
* R2 = 0.41 means more than half of savings variation is unexplained; the text calls this "reasonably well".
* GANs are in the title and abstract but no GAN architecture, training or effect on accuracy is reported.

## What would make a fair comparison possible

1. Add a **savings-prediction** module to this project and report MAE / RMSE / R2 on a public or self-collected survey (the 11 questions in the paper's Table I can be reused).
2. Add an **LLM explanation layer** and measure it with the same kind of user survey, with n and rubric stated.
3. Collect and label **real SMS** (consented, your own and friends') and report accuracy on that instead of synthetic data.
