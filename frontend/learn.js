/* Learn finance: a guided path (short lessons, your own numbers, a quick quiz each) with the full dictionary underneath.
   Loaded after app.js. Replaces the old "Know your money" page but keeps its id so term links (#know?t=emi) still work. */

const LESSONS = [
  { id: 'flow', level: 'Start here', min: 3, title: 'Where your money goes',
    body: ['Income is what comes in. Expenses are what goes out. What is left is your **savings**, and the share you keep is your **savings rate**.',
      'A simple starting split is **50-30-20**: about 50% on needs (rent, food, bills, EMI), 30% on wants, 20% to savings and investing. It is a guide, not a rule. Any saving beats none.',
      'Step one is just seeing it. The Activity tab already sorts every bank message into categories for you.'],
    yours: p => p.monthly_salary ? `You earn about ${inr(p.monthly_salary)} and spend about ${inr(p.monthly_expenses)} a month, so roughly ${Math.max(0, Math.round(100 * (p.monthly_salary - p.monthly_expenses) / p.monthly_salary))}% is left over.` : 'Add your monthly income in Profile to see your own savings rate here.',
    quiz: { q: 'Your income is ₹50,000 and you spend ₹40,000. What is your savings rate?', o: ['10%', '20%', '40%'], a: 1, why: '₹10,000 saved out of ₹50,000 is 20%.' },
    ask: 'Am I saving enough each month? How does my spending compare with the 50-30-20 guide?' },
  { id: 'emergency', level: 'Start here', min: 3, title: 'Emergency fund and safety buffer',
    body: ['An **emergency fund** is cash you can reach quickly for job loss, illness or a big repair. Common advice is **3 to 6 months of spending**, more if your income is irregular.',
      'Keep it in a savings account, liquid fund or short FD, not in shares. Its job is to be there, not to grow.',
      'This app calls it the **safety buffer** and subtracts it before telling you what is safe to invest.'],
    yours: p => { const liq = (p.current_balance || 0) + (p.savings_other || 0); return p.monthly_expenses ? `Your bank balance plus other savings is ${inr(liq)}, enough for about ${(liq / p.monthly_expenses).toFixed(1)} months of spending.` : 'Add your monthly spending in Profile to see your months of cover.'; },
    quiz: { q: 'Which is the best place for an emergency fund?', o: ['Small-cap shares', 'A savings account or liquid fund', 'Gold jewellery'], a: 1, why: 'Safety and quick access matter more than returns here.' },
    ask: 'Is my emergency fund big enough? What should I do if not?' },
  { id: 'loans', level: 'Core', min: 4, title: 'Loans and EMIs',
    body: ['An **EMI** is a fixed monthly payment that covers both interest and part of the loan. Early on, most of each EMI is interest.',
      'A healthy rule of thumb: total EMIs under about **40% of monthly income**. Above that, one bad month hurts.',
      'Prepay or invest? If your loan interest is higher than what you can safely earn after tax, prepaying is a guaranteed return. If it is lower, investing may win. A home loan also gives tax benefits, which changes the maths.'],
    yours: p => p.loan_emi && p.monthly_salary ? `Your EMI is ${inr(p.loan_emi)}, which is ${Math.round(100 * p.loan_emi / p.monthly_salary)}% of your income, and you still owe ${inr(p.loan_outstanding)}.` : 'No loan on record. If you add one in Profile, your EMI share shows here.',
    quiz: { q: 'You earn ₹60,000 and pay ₹30,000 in EMIs. Is that comfortable?', o: ['Yes, it is under 40%', 'No, it is 50%, which is too high', 'It does not matter'], a: 1, why: '₹30,000 of ₹60,000 is 50%, above the usual 40% guide.' },
    ask: 'Should I prepay my loan or invest the extra money? Use my numbers.' },
  { id: 'tax', level: 'Core', min: 4, title: 'Income tax basics: old vs new regime',
    body: ['India taxes income in **slabs**: the higher your income, the higher the rate on the top part. You do not pay the top rate on all of it.',
      'There are two ways to file. The **new regime** has lower rates and few deductions. The **old regime** has higher rates but lets you subtract deductions such as 80C, 80D and home-loan interest. Which is cheaper depends on how much you can deduct.',
      'Salaried people also get a **standard deduction**, and low incomes may get a **rebate (87A)**. Rules change most years, so treat any figure as an estimate and confirm with a chartered accountant.'],
    yours: () => 'The Tax tab compares both regimes on your income and shows which one saves you more.',
    quiz: { q: 'Which regime lets you claim 80C and 80D deductions?', o: ['Old regime', 'New regime', 'Both equally'], a: 0, why: 'The new regime trades most deductions for lower rates.' },
    ask: 'Which tax regime is better for me and why? Show the comparison.' },
  { id: 'save-tax', level: 'Core', min: 4, title: 'Saving tax legally',
    body: ['In the old regime, these cut your taxable income: **80C** (up to ₹1,50,000: PPF, ELSS, life insurance, tuition), **80D** (health insurance), **NPS 80CCD(1B)** (extra ₹50,000) and **home-loan interest** (up to ₹2,00,000).',
      'Do not buy a product only for the tax break. Pick what you would want anyway, then let the deduction be a bonus.',
      'If the new regime is cheaper for you, extra deductions will not lower your bill. The Overview page tells you which case you are in.'],
    yours: () => 'The Overview page shows how much room you have left under each section this year.',
    quiz: { q: 'What is a good reason to invest in an 80C product?', o: ['Only because it saves tax', 'It fits your goals and also saves tax', 'Everyone must buy one'], a: 1, why: 'A tax break is a bonus, not a reason by itself.' },
    ask: 'How can I save more tax this year? What room do I have left?' },
  { id: 'invest', level: 'Grow', min: 5, title: 'Investing basics',
    body: ['**Risk and return go together.** Shares can grow faster but swing a lot. Debt and fixed deposits are steadier but grow slower. Inflation (about 5-6% a year) quietly eats cash that sits idle.',
      'A **SIP** invests a fixed amount every month, so you buy more when prices are low and less when high. It also builds the habit.',
      '**Time horizon** decides the mix: money needed within 3 years should stay safe; money for 7+ years can take more risk. Spread across a few types (diversify) instead of betting on one.',
      'This app never recommends specific shares or funds. It shows how much is safe to invest after tax and your buffer.'],
    yours: p => p.investments_value ? `You have about ${inr(p.investments_value)} invested${p.investments_note ? ' (' + p.investments_note + ')' : ''}.` : 'Nothing invested on record. The Plan tab shows what is safe to invest each month.',
    quiz: { q: 'You need money for a house deposit in 2 years. Where should it mostly sit?', o: ['Safe, low-risk options', 'Risky shares for faster growth', 'It does not matter'], a: 0, why: 'A short horizon cannot ride out a market fall.' },
    ask: 'How much can I safely invest each month, and how should I think about splitting it?' },
  { id: 'advance', level: 'Grow', min: 3, title: 'Advance tax and uneven income',
    body: ['If you owe more than ₹10,000 in tax for the year after tax already deducted (TDS), you pay it in instalments called **advance tax**: by 15 June, 15 September, 15 December and 15 March.',
      'Freelancers feel this most, because income is lumpy and no employer deducts tax. Setting tax aside from every payment, as soon as it arrives, avoids a nasty bill and interest.',
      'That is why the Plan tab holds back tax first, then your safety buffer, and only then shows what is safe to invest.'],
    yours: () => 'The Advance tax tab lists the four dates and how much to set aside for each.',
    quiz: { q: 'A client pays you ₹1,00,000. What is the smart first move?', o: ['Spend it, deal with tax later', 'Set aside an estimated tax share right away', 'Invest all of it'], a: 1, why: 'Reserving tax first means the due date never surprises you.' },
    ask: 'When is my next advance tax due and how much should I set aside?' },
];

const learnDone = () => { try { return new Set(JSON.parse(localStorage.getItem('copilot_learn') || '[]')); } catch (_) { return new Set(); } };
const learnSave = s => { try { localStorage.setItem('copilot_learn', JSON.stringify([...s])); } catch (_) {} };
const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');

const _oldKnow = renderKnow;
async function renderLearn() {
  const [p, dict] = await Promise.all([api('/profile'), _oldKnow()]);
  const done = learnDone(), nextIdx = Math.max(0, LESSONS.findIndex(l => !done.has(l.id))), pct = Math.round(100 * done.size / LESSONS.length);
  return `<section class="card"><div class="card-head"><div><h2>Your learning path</h2><p class="sub">${LESSONS.length} short lessons, about ${LESSONS.reduce((a, l) => a + l.min, 0)} minutes in total. Each shows <b>your own numbers</b>, then a one-question check. Finish them in order, or jump to what you need.</p></div></div>
    <div style="height:8px;border-radius:99px;background:var(--line);overflow:hidden;margin:14px 0 6px"><div id="lbar" style="height:100%;width:${pct}%;background:var(--brand);transition:width .3s"></div></div>
    <p class="sub" id="ltxt" style="font-size:13px">${done.size} of ${LESSONS.length} done${done.size === LESSONS.length ? ' · well done! Ask the co-pilot to put it all into a plan for you.' : ''}</p>
    ${LESSONS.map((l, i) => `<details class="term lesson" id="les-${l.id}" ${i === nextIdx && done.size < LESSONS.length ? 'open' : ''}>
      <summary><span class="lnum">${done.has(l.id) ? '✅' : (i + 1) + '.'}</span> ${esc(l.title)} <span class="chip ${l.level === 'Start here' ? 'good' : l.level === 'Core' ? 'brand' : 'gold'}" style="margin-left:6px;font-weight:600">${l.level} · ${l.min} min</span></summary>
      ${l.body.map(t => `<p>${md(t)}</p>`).join('')}
      <div class="callout brand" style="margin:10px 0">${ICON.info}<span><b>In your life:</b> ${esc(l.yours(p))}</span></div>
      <div class="quiz" data-lesson="${l.id}"><p style="font-weight:700;margin:12px 0 6px">Quick check: ${esc(l.quiz.q)}</p>
        <div class="chips-row">${l.quiz.o.map((o, k) => `<button type="button" class="sample" data-quiz="${l.id}:${k}">${esc(o)}</button>`).join('')}</div><p class="sub qres" style="margin-top:8px"></p></div>
      <button type="button" class="btn small" data-learnask="${l.id}" style="margin-top:8px">Ask the co-pilot about this</button></details>`).join('')}
  </section>
  <h2 style="margin:26px 0 4px;font-size:18px">Dictionary</h2><p class="sub" style="margin-bottom:6px">Every money word in the app, explained from zero.</p>${dict.replace('<div class="card"><h2>Start here</h2>', '<div class="card"><h2>Look up a word</h2>')}`;
}
const learnPage = PAGES.find(p => p.id === 'know');
Object.assign(learnPage, { id: 'know', label: 'Learn', icon: 'info', title: 'Learn finance', primary: true,
  sub: 'Short lessons on money, tax and investing, using your own numbers. Start at lesson 1.', render: renderLearn });
const _oldAfter = learnPage.after;
learnPage.after = v => { if (_oldAfter) _oldAfter(v); };

document.addEventListener('click', e => {
  const q = e.target.closest('[data-quiz]');
  if (q) {
    const [id, k] = q.dataset.quiz.split(':'), l = LESSONS.find(x => x.id === id), box = q.closest('.quiz'), ok = +k === l.quiz.a;
    box.querySelectorAll('[data-quiz]').forEach(b => b.setAttribute('aria-pressed', b === q));
    box.querySelector('.qres').innerHTML = ok ? `✅ <b>Correct.</b> ${esc(l.quiz.why)}` : `Not quite. ${esc(l.quiz.why)} Try another answer.`;
    if (ok) { const d = learnDone(); d.add(id); learnSave(d); q.closest('details').querySelector('.lnum').textContent = '✅';
      $('#lbar').style.width = Math.round(100 * d.size / LESSONS.length) + '%'; $('#ltxt').textContent = `${d.size} of ${LESSONS.length} done`; }
    return;
  }
  const a = e.target.closest('[data-learnask]');
  if (a) { window.pendingAsk = LESSONS.find(x => x.id === a.dataset.learnask).ask; location.hash = '#ask'; }
});
