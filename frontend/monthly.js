/* Monthly plan page: month-by-month cash, tax and investing decisions (data from GET /plan/monthly). */
const STRATEGY_TXT = { even: 'Spread evenly', asap: 'As early as safe', late: 'Jan to Mar only' };
const mv = v => (v === null || v === undefined) ? '-' : inr(v);

function cashChart(rows, buffer) {
  const live = rows.filter(r => r.status !== 'past');
  if (!live.length) return '';
  const w = 620, h = 210, padL = 26, padB = 24, n = live.length;
  const vals = live.flatMap(r => [r.cash_end_conservative, r.cash_end_expected, buffer]);
  const lo = Math.min(0, ...vals), hi = Math.max(...vals, 1) * 1.1;
  const x = i => padL + (n === 1 ? (w - 2 * padL) / 2 : i * (w - 2 * padL) / (n - 1));
  const y = v => 10 + (h - padB - 10) * (1 - (v - lo) / (hi - lo));
  const path = k => live.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`).join(' ');
  const labels = live.map((r, i) => `<text x="${x(i)}" y="${h - 6}" text-anchor="middle">${esc(r.label.slice(0, 3))}</text>`).join('');
  const dots = live.map((r, i) => `<circle cx="${x(i)}" cy="${y(r.cash_end_conservative)}" r="4" fill="${r.below_buffer ? '#d04545' : '#0b7a75'}"><title>${esc(r.label)}: ${inr(r.cash_end_conservative)} (cautious)</title></circle>`).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Projected cash at each month end">
    <line x1="0" x2="${w}" y1="${y(buffer)}" y2="${y(buffer)}" stroke="#f0a93b" stroke-width="2" stroke-dasharray="6 5"/>
    <text x="${w}" y="${y(buffer) - 6}" text-anchor="end">buffer ${inrC(buffer)}</text>
    <path d="${path('cash_end_expected')}" fill="none" stroke="#8fa3b8" stroke-width="2.2" stroke-dasharray="2 4"/>
    <path d="${path('cash_end_conservative')}" fill="none" stroke="#0b7a75" stroke-width="3"/>${dots}${labels}</svg>
    <p class="sub legend-line"><span class="swatch" style="background:#0b7a75"></span>Cautious path <span class="swatch dotted"></span>Expected path <span class="swatch" style="background:#f0a93b"></span>Safety buffer</p>`;
}

function monthCard(r) {
  const past = r.status === 'past', cur = r.status === 'current';
  const chip = past ? '<span class="chip">Done</span>' : cur ? '<span class="chip brand">This month</span>' : '<span class="chip blue">Planned</span>';
  if (past) {
    return `<article class="mcard past"><header><h3>${esc(r.label)}</h3>${chip}</header>
      <dl class="mgrid"><div><dt>Income</dt><dd>${r.income_actual == null ? 'not recorded' : inr(r.income_actual)}</dd></div>
      <div><dt>Expected</dt><dd>${inr(r.income_expected)}</dd></div>
      <div><dt>Spent</dt><dd>${r.expenses_actual == null ? 'not recorded' : inr(r.expenses_actual)}</dd></div>
      <div><dt>Invested for tax</dt><dd>${inr(r.invested_actual)}</dd></div></dl></article>`;
  }
  const split = Object.entries(r.tax_saving_split || {}).filter(([, v]) => v > 0).map(([s, v]) => `${SECTION_NAME[s] || s}: ${inr(v)}`).join(' · ');
  return `<article class="mcard ${cur ? 'cur' : ''} ${r.below_buffer ? 'tight' : ''}"><header><h3>${esc(r.label)}</h3>${chip}
    ${r.below_buffer ? '<span class="chip warn">Below buffer</span>' : ''}</header>
    <div class="mhero"><div><span>Safe to invest</span><b>${inr(r.safe_to_invest)}</b></div>
      <div><span>Tax-saving to invest</span><b>${inr(r.tax_saving_invest)}</b>${split ? `<small>${esc(split)}</small>` : ''}</div></div>
    <dl class="mgrid"><div><dt>Income ${r.income_actual != null ? '(so far)' : '(cautious)'}</dt><dd>${inr(r.income_actual != null ? r.income_actual : r.income_conservative)}</dd></div>
      <div><dt>Expected income</dt><dd>${inr(r.income_expected)}</dd></div>
      <div><dt>Spending</dt><dd>${inr(r.expenses_conservative)}</dd></div>
      <div><dt>Known bills</dt><dd>${inr(r.bills)}</dd></div>
      ${r.advance_tax_due ? `<div class="hl"><dt>Advance tax due</dt><dd>${inr(r.advance_tax_due)}</dd></div>` : ''}
      <div><dt>Cash at month end</dt><dd>${inr(r.cash_end_conservative)}<small>cautious</small></dd></div>
      <div><dt>Tax-saving room left</dt><dd>${inr(r.tax_room_left_after)}</dd></div></dl>
    <details class="why"><summary>Why this number?</summary><ul>${(r.why || []).map(w => `<li>${esc(w)}</li>`).join('')}
      ${r.advance_tax_note ? `<li>${esc(r.advance_tax_note)}</li>` : ''}</ul></details></article>`;
}

function assumptionForm(a) {
  const v = k => (a && a[k] != null) ? a[k] : '';
  return `<form id="asmForm" class="form-grid">
    ${field('as_buf', 'Safety buffer (months of spending)', v('buffer_months'), { step: '0.5', help: 'Leave blank to use your profile.' })}
    <div class="field"><label for="as_alpha">Caution level</label><select class="input" id="as_alpha"><option value="">Use profile</option>
      ${[[0.8, 'Relaxed (80%)'], [0.9, 'Balanced (90%)'], [0.95, 'Careful (95%)'], [0.99, 'Very careful (99%)']].map(([x, l]) => `<option value="${x}">${l}</option>`).join('')}</select></div>
    <div class="field"><label for="as_strat">When to invest</label><select class="input" id="as_strat"><option value="">Use default</option>
      ${Object.entries(STRATEGY_TXT).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></div>
    ${field('as_inc', 'Expected monthly income', v('expected_income_override'), { prefix: '₹', help: 'Overrides what your history says.' })}
    ${field('as_exp', 'Expected monthly spending', v('expected_expense_override'), { prefix: '₹' })}
    ${field('as_shock', 'What if future income changes by %', v('income_shock_pct'), { step: '1', help: 'For example -30 for a slow quarter.' })}
    ${field('as_over', 'Spending overrun allowance %', v('expense_overrun_pct'), { step: '1' })}
    ${field('as_biz', 'Business costs as % of receipts', v('business_expense_pct'), { step: '1', help: 'Self-employed only.' })}
    <label class="check full"><input type="checkbox" id="as_44"> Use presumptive taxation (44ADA, 50% of receipts). Check eligibility with a professional.</label>
    <div class="full row-actions"><button class="btn primary" type="submit">Compare with my saved plan</button><button class="btn" type="button" id="asReset">Reset</button></div></form>`;
}
function collectAssumptions() {
  const num = id => { const x = $('#' + id).value; return x === '' ? undefined : +x; };
  const o = { buffer_months: num('as_buf'), alpha: num('as_alpha'), strategy: $('#as_strat').value || undefined,
    expected_income_override: num('as_inc'), expected_expense_override: num('as_exp'), income_shock_pct: num('as_shock'),
    expense_overrun_pct: num('as_over'), business_expense_pct: num('as_biz'), presumptive_44ada: $('#as_44').checked || undefined };
  Object.keys(o).forEach(k => o[k] === undefined && delete o[k]);
  return o;
}
function diffTable(c) {
  const L = { estimated_tax: ['Estimated tax', 1], tax_saving_invest_total: ['Tax-saving invested', 0], tax_saved_by_plan: ['Tax saved by plan', 0],
    min_cash_conservative: ['Lowest cautious cash', 0], safe_now: ['Safe to invest now', 0], advance_tax_total_scheduled: ['Advance tax scheduled', 1],
    projected_annual_income: ['Projected yearly income', 0], months_with_zero_safe: ['Months with nothing safe to invest', 1] };
  const b = c.baseline.summary, s = c.scenario.summary;
  const rows = Object.entries(L).filter(([k]) => b[k] != null && s[k] != null).map(([k, [lab, badUp]]) => {
    const d = s[k] - b[k], cls = d === 0 ? '' : ((d > 0) === !!badUp ? 'bad-t' : 'good-t');
    const f = k === 'months_with_zero_safe' ? (x => x) : inr;
    return `<tr><td>${lab}</td><td>${f(b[k])}</td><td>${f(s[k])}</td><td class="${cls}">${d > 0 ? '+' : ''}${k === 'months_with_zero_safe' ? d : inr(d)}</td></tr>`;
  }).join('');
  return `<div class="tablewrap"><table class="table"><thead><tr><th></th><th>Saved</th><th>What-if</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function renderMonthly() {
  const [p, bills] = await Promise.all([api('/plan/monthly'), api('/bills')]);
  const S = p.summary, rows = p.months, cur = rows.find(r => r.status === 'current') || {};
  const buffer = (rows.find(r => r.buffer != null) || {}).buffer || 0;
  const miss = p.missing_data || [];
  const warn = [...(miss.length ? [`Missing data: ${miss.join(' and ')}. Numbers below are cautious estimates, not facts.`] : []), ...(p.warnings || [])];
  const u = p.uncertainty || {};
  const y = p.ytd || {};
  return `
  ${warn.map(w => `<div class="callout gold" style="margin-bottom:10px">${ICON.info}<span>${esc(w)}</span></div>`).join('')}
  <div class="grid g4">
    <section class="card hero mini"><div class="lbl">Safe to invest this month</div><div class="big">${inr(cur.safe_to_invest || 0)}</div>
      <p class="say">${cur.tax_saving_invest ? `Of this, ${inr(cur.tax_saving_invest)} also lowers your tax.` : 'Nothing here lowers your tax. Invest only for your own goals.'}</p></section>
    <section class="card stat"><div class="lbl">Tax for ${esc(S.fy)}</div><div class="val">${inr(S.estimated_tax)}</div><div class="note">${S.recommended_regime === 'new' ? 'New' : 'Old'} regime · on ${inrC(S.projected_annual_income)}</div></section>
    <section class="card stat"><div class="lbl">Advance tax still to pay</div><div class="val">${inr(S.advance_tax_total_scheduled)}</div><div class="note">Reserved before any investing</div></section>
    <section class="card stat"><div class="lbl">Tax-saving room left</div><div class="val">${inr(S.tax_room_end)}</div><div class="note">${S.tax_saved_by_plan ? `Plan saves ${inr(S.tax_saved_by_plan)}` : 'No tax saved by investing'}</div></section>
  </div>
  <section class="card" style="margin-top:18px"><div class="card-head"><div><h2>Cash month by month</h2><p class="sub">The cautious path assumes a bad-but-plausible month. Investing only happens while it stays above your buffer.</p></div>
    <span class="chip">${esc(STRATEGY_TXT[S.strategy] || S.strategy)}</span></div>${cashChart(rows, buffer)}</section>
  <div class="grid g2" style="margin-top:18px">
    <section class="card"><h2>Year to date</h2><dl class="kvlist">
      <div><dt>Income received (past months)</dt><dd>${inr(y.income_actual_past_months)}</dd></div>
      <div><dt>Expected for the same months</dt><dd>${inr(y.income_expected_past_months)}</dd></div>
      <div><dt>Versus expectation</dt><dd>${y.income_variance_pct == null ? '-' : (y.income_variance_pct > 0 ? '+' : '') + y.income_variance_pct + '%'}</dd></div>
      <div><dt>Tax-saving invested so far</dt><dd>${inr(y.tax_saving_invested_ytd)}</dd></div>
      <div><dt>Advance tax paid</dt><dd>${inr(y.advance_tax_paid)}</dd></div>
      <div><dt>Months with data (income / spending)</dt><dd>${y.months_with_income_data} / ${y.months_with_expense_data} of ${y.months_elapsed}</dd></div></dl></section>
    <section class="card"><h2>How sure are we?</h2><p class="sub">Typical month of income, from your history.</p>
      <div class="range"><div><span>Bad month (10%)</span><b>${inrC(u.monthly_income_p10)}</b></div><div><span>Typical</span><b>${inrC(u.monthly_income_p50)}</b></div><div><span>Good month (90%)</span><b>${inrC(u.monthly_income_p90)}</b></div></div>
      <p class="sub" style="margin-top:10px">Wider gaps mean the plan is more cautious. Spread (sigma) ${u.sigma ?? '-'}.</p></section>
  </div>
  <h2 class="sec">The 12 months</h2><div class="mlist">${rows.map(monthCard).join('')}</div>
  <section class="card" style="margin-top:18px"><h2>Change an assumption and compare</h2><p class="sub">Nothing here is saved. It re-runs the plan and shows the difference.</p>
    <div style="margin-top:14px">${assumptionForm()}</div><div id="asmOut" style="margin-top:16px"></div></section>
  <section class="card" style="margin-top:18px"><h2>Known upcoming bills</h2><p class="sub">Bills reduce what is safe to invest in the month they fall due.</p>
    <form id="billForm" class="form-grid" style="margin-top:12px"><div class="field"><label for="b_month">Month</label><input class="input" id="b_month" type="month" required></div>
      <div class="field"><label for="b_name">What for</label><input class="input" id="b_name" maxlength="80" placeholder="School fees"></div>${field('b_amt', 'Amount', '', { prefix: '₹' })}
      <label class="check"><input type="checkbox" id="b_rep"> Repeats every month</label><div class="full"><button class="btn" type="submit">Add bill</button></div></form>
    <div class="tablewrap"><table class="table" style="margin-top:12px"><tbody>${bills.map(b => `<tr><td>${esc(b.month)}</td><td>${esc(b.name || 'Bill')}${b.repeat_monthly ? ' <span class="chip">monthly</span>' : ''}</td><td style="text-align:right"><b>${inr(b.amount)}</b></td>
      <td style="text-align:right"><button class="btn small" data-delbill="${b.id}">Remove</button></td></tr>`).join('') || '<tr><td>No bills added.</td></tr>'}</tbody></table></div></section>
  <details class="card assump" style="margin-top:18px"><summary><h2 style="display:inline">Inputs and assumptions used</h2></summary>
    <div class="tablewrap"><table class="table"><thead><tr><th>Input</th><th>Value</th><th>Source</th></tr></thead><tbody>${(p.assumptions || []).map(a => `<tr><td>${esc(a.label)}</td><td>${esc(a.value)}</td><td>${esc(a.source)}</td></tr>`).join('')}</tbody></table></div>
    <ul class="limits">${(p.limits || []).map(l => `<li>${esc(l)}</li>`).join('')}</ul></details>`;
}
function monthlyAfter() {
  const f = $('#asmForm'); if (!f) return;
  f.onsubmit = async e => { e.preventDefault(); const o = collectAssumptions();
    if (!Object.keys(o).length) { toast('Change at least one assumption first', true); return; }
    try { const c = await api('/plan/monthly/compare', { method: 'POST', body: o });
      const sc = c.scenario.months.filter(r => r.status !== 'past');
      $('#asmOut').innerHTML = `<h3 style="font:700 15px var(--display);margin-bottom:8px">Difference</h3>${diffTable(c)}
        <p class="sub" style="margin:10px 0 6px">What-if safe-to-invest by month</p><div class="chiprow">${sc.map(r => `<span class="chip">${esc(r.label.slice(0, 3))} ${inrC(r.safe_to_invest)}</span>`).join('')}</div>`;
    } catch (err) { toast(err.message, true); } };
  $('#asReset').onclick = () => { f.reset(); $('#asmOut').innerHTML = ''; };
  $('#billForm').onsubmit = async e => { e.preventDefault();
    try { await api('/bills', { method: 'POST', body: { month: $('#b_month').value, name: $('#b_name').value, amount: +$('#b_amt').value, repeat_monthly: $('#b_rep').checked } }); toast('Bill added'); route(); }
    catch (err) { toast(err.message, true); } };
}
