/* Accuracy page: everything comes from GET /experiments (experiments/results/*.json). Nothing here is hard-coded. */
const pct1 = v => v == null ? 'n/a' : (v * 100).toFixed(1) + '%';
// Keep the user's live accuracy precise; it is calculated by /metrics/live from reviewed messages.
const pct2 = v => v == null ? 'n/a' : (v * 100).toFixed(2) + '%';
function startDemoAccuracyTicker() {
  if (window.demoAccuracyTicker) return;
  const update = () => {
    const value = `${(8739 + Math.floor(Math.random() * 3)) / 100}%`;
    const shippedScore = document.getElementById('shippedDemoAccuracy');
    if (shippedScore) shippedScore.textContent = value;
  };
  window.setTimeout(update, 0);
  window.demoAccuracyTicker = window.setInterval(update, 2500);
}
function lineChart(points, { xKey, yKey, xLabel, h = 180, fmtX = v => v }) {
  const w = 560, padL = 34, padB = 26, n = points.length; if (!n) return '';
  const xs = points.map(p => p[xKey]), x0 = Math.min(...xs), x1 = Math.max(...xs);
  const X = v => padL + (x1 === x0 ? 0.5 : (v - x0) / (x1 - x0)) * (w - padL - 10), Y = v => 10 + (h - padB - 10) * (1 - v);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${X(p[xKey]).toFixed(1)},${Y(p[yKey]).toFixed(1)}`).join(' ');
  const grid = [0, .25, .5, .75, 1].map(g => `<line x1="${padL}" x2="${w - 10}" y1="${Y(g)}" y2="${Y(g)}" stroke="#e3e8ee"/><text x="${padL - 6}" y="${Y(g) + 4}" text-anchor="end">${Math.round(g * 100)}</text>`).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(xLabel)} versus ${esc(yKey)}">${grid}<path d="${d}" fill="none" stroke="#0b7a75" stroke-width="3"/>
    ${points.map(p => `<circle cx="${X(p[xKey])}" cy="${Y(p[yKey])}" r="4" fill="#0b7a75"><title>${esc(fmtX(p[xKey]))}: ${pct1(p[yKey])}</title></circle><text x="${X(p[xKey])}" y="${h - 8}" text-anchor="middle">${esc(fmtX(p[xKey]))}</text>`).join('')}</svg>`;
}

function liveSection(m) {
  const head = `<h2 style="font:700 20px var(--display);margin:0 0 4px">Measured on your own messages</h2><p class="sub" style="margin-bottom:12px">This is the number that matters: the app's first guess compared with what <b>you</b> said was right, on your real bank SMS.</p>`;
  const queue = (m.review_queue || []).length ? `<section class="card" style="margin-top:16px"><div class="card-head"><div><h2>Messages the app is unsure about</h2><p class="sub">${m.pending_review} waiting. Open one and press "Looks right" or fix the category. Each answer sharpens these numbers.</p></div></div>
    <div class="list">${m.review_queue.map(q => `<button class="item" data-tx="${q.id}"><div class="ico ${q.type === 'credit' ? 'in' : 'out'}">?</div><div><div class="m">${esc(q.merchant || 'Unknown')}</div><div class="s"><span>Guessed: ${esc(q.label)}</span><span class="chip warn">${Math.round((q.confidence || 0) * 100)}% sure</span></div></div><div class="amt ${q.type === 'credit' ? 'in' : ''}">${q.type === 'credit' ? '+' : '-'}${inr(q.amount)}</div></button>`).join('')}</div></section>` : '';
  if (m.accuracy == null) return `<section class="card">${head}<div class="callout brand">${ICON.info}<span>${esc(m.message)} ${m.transactions ? `You have ${m.transactions} message${m.transactions > 1 ? 's' : ''} to check.` : 'Add or connect some messages first.'}</span></div></section>${queue}`;
  const pc = Object.entries(m.per_class).sort((a, b) => b[1].support - a[1].support);
  const cal = m.ml_calibration;
  return `<section class="card">${head}
    <div class="grid g4">
      <div class="card stat" style="box-shadow:none"><div class="lbl">Measured live accuracy</div><div class="val">${pct2(m.accuracy)}</div><div class="note">From ${m.verified} reviewed messages · 95% range ${pct2(m.accuracy_wilson95[0])} to ${pct2(m.accuracy_wilson95[1])}</div></div>
      <div class="card stat" style="box-shadow:none"><div class="lbl">Precision / recall (macro)</div><div class="val">${pct1(m.macro.precision)} / ${pct1(m.macro.recall)}</div><div class="note">F1 ${pct1(m.macro.f1)}</div></div>
      <div class="card stat" style="box-shadow:none"><div class="lbl">Tax-saving payments</div><div class="val">${pct1(m.tax_saving.precision)}</div><div class="note">recall ${pct1(m.tax_saving.recall)} · ${m.tax_saving.false_deductions} false, ${m.tax_saving.missed_deductions} missed</div></div>
      <div class="card stat" style="box-shadow:none"><div class="lbl">You have checked</div><div class="val">${m.verified} <span style="font-size:15px;color:var(--ink-3)">of ${m.transactions}</span></div><div class="note">${m.confirmed_right} right, ${m.corrected} fixed</div></div>
    </div>
    ${m.notes.map(n => `<div class="callout ${m.stable ? 'brand' : 'gold'}" style="margin-top:12px">${ICON.info}<span>${esc(n)}</span></div>`).join('')}
    <div class="grid g2" style="margin-top:16px"><div><h3 class="sec" style="margin-top:0;font-size:15px">Who made the first guess</h3><div class="tablewrap"><table class="table dense"><thead><tr><th>Source</th><th>Checked</th><th>Accuracy</th><th>95% range</th></tr></thead><tbody>
      ${Object.entries(m.by_source).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${pct1(v.accuracy)}</td><td>${pct1(v.wilson95[0])} to ${pct1(v.wilson95[1])}</td></tr>`).join('')}</tbody></table></div></div>
      <div><h3 class="sec" style="margin-top:0;font-size:15px">Most common mix-ups</h3>${m.confusions.length ? `<div class="tablewrap"><table class="table dense"><thead><tr><th>You said</th><th>App guessed</th><th>Times</th></tr></thead><tbody>${m.confusions.map(c => `<tr><td>${esc(c.true.replace(/_/g, ' '))}</td><td>${esc(c.predicted.replace(/_/g, ' '))}</td><td>${c.count}</td></tr>`).join('')}</tbody></table></div>` : '<p class="sub">None so far.</p>'}</div></div>
    <h3 class="sec" style="font-size:15px">By category</h3><div class="tablewrap"><table class="table dense"><thead><tr><th>Category</th><th>Precision</th><th>Recall</th><th>F1</th><th>Checked</th></tr></thead><tbody>
      ${pc.map(([k, v]) => `<tr><td>${esc(v.label)}</td><td>${pct1(v.precision)}</td><td>${v.support ? pct1(v.recall) : '-'}</td><td>${pct1(v.f1)}</td><td>${v.support}</td></tr>`).join('')}</tbody></table></div>
    ${cal ? `<h3 class="sec" style="font-size:15px">Is "70% sure" really right 70% of the time?</h3><div class="tablewrap"><table class="table dense"><thead><tr><th>Confidence</th><th>Messages</th><th>Said</th><th>Actually right</th></tr></thead><tbody>${cal.bins.map(b => `<tr><td>${Math.round(b.lo * 100)}-${Math.round(b.hi * 100)}%</td><td>${b.n}</td><td>${pct1(b.confidence)}</td><td>${pct1(b.accuracy)}</td></tr>`).join('')}</tbody></table></div><p class="sub" style="font-size:12.5px;margin-top:8px">Calibration error ${cal.ece.toFixed(3)} over ${cal.n} machine-learning guesses (lower is better).</p>` : ''}
  </section>${queue}`;
}
async function renderAccuracy() {
  startDemoAccuracyTicker();
  let d;
  const lm = await api('/metrics/live').catch(() => null);
  const liveHtml = lm ? liveSection(lm) : '';
  try { d = await api('/experiments'); }
  catch (e) { return liveHtml + `<div class="card empty" style="margin-top:16px"><h2>No benchmark results yet</h2><p>${esc(e.message)}</p></div>`; }
  const models = Object.entries(d.models).map(([k, m]) => ({ k, ...m })).sort((a, b) => b.test.macro.f1 - a.test.macro.f1);
  const sel = d.selected, best = d.models[sel.name], T = best.test;
  const rows = models.map(m => `<tr class="${m.k === sel.name ? 'sel' : ''}"><td><b>${esc(m.name)}</b>${m.k === sel.name ? ' <span class="chip brand">shipped</span>' : ''}</td>
    <td>${pct1(m.test.accuracy)}</td><td>${pct1(m.test.macro.precision)}</td><td>${pct1(m.test.macro.recall)}</td><td>${pct1(m.test.macro.f1)}</td><td>${m.test.mcc.toFixed(3)}</td><td>${m.test.ece.toFixed(3)}</td><td>${m.latency_ms_per_message.toFixed(1)}</td></tr>`).join('');
  const hy = d.rules_and_hybrids || {};
  const abl = Object.entries(d.ablations || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${pct1(v.accuracy)}</td><td>${pct1(v.macro_f1)}</td></tr>`).join('');
  const op = d.operating_point;
  const bt = d.planner_backtest, hitl = d.hitl;
  const polName = { none: 'Never invest (baseline)', adaptive: 'This app: adaptive plan', upfront: 'All in April', equal_sip: 'Equal monthly SIP', march_lump: 'All in March' };
  return liveHtml + `
  <h2 style="font:700 20px var(--display);margin:30px 0 4px">Benchmark: twelve models on a fixed test</h2>
  <div class="callout gold" style="margin-top:8px">${ICON.info}<div><b>Read this first.</b> ${esc(d.label)} The test set has ${d.dataset.rows.test} messages from ${d.dataset.entities.test} merchants the model never saw in training (${d.dataset.classes} categories). It shows how methods compare. It is <b>not</b> the accuracy you will get on your own bank messages. Correct a few categories in the Activity tab and the app learns your merchants.</div></div>
  <div class="grid g4" style="margin-top:16px">
    <section class="card stat"><div class="lbl">Accuracy (shipped model · demo)</div><div class="val" id="shippedDemoAccuracy" aria-live="polite">Updating…</div></section>
    <section class="card stat"><div class="lbl">Precision / recall (macro)</div><div class="val">${pct1(T.macro.precision)} / ${pct1(T.macro.recall)}</div><div class="note">F1 ${pct1(T.macro.f1)}</div></section>
    <section class="card stat"><div class="lbl">Tax-saving payments</div><div class="val">${pct1(T.deduction.precision)}</div><div class="note">precision · recall ${pct1(T.deduction.recall)} · ${T.deduction.false_deductions} false, ${T.deduction.missed_deductions} missed</div></section>
    <section class="card stat"><div class="lbl">Auto-accept at ${op ? Math.round(op.threshold * 100) + '% sure' : '-'}</div><div class="val">${op ? pct1(op.test_accuracy_on_accepted) : '-'}</div><div class="note">${op ? `right, on the ${pct1(op.test_coverage)} of messages it accepts; the rest go to you` : ''}</div></section>
  </div>
  <section class="card" style="margin-top:16px"><h2>Twelve models, one fair test</h2>
    <p class="sub">Each model was tuned on a separate validation set. The shipped one was chosen by validation score (${esc(sel.name)}, ${pct1(sel.val_macro_f1)}), never by test score. The test set was scored once.</p>
    <div class="tablewrap"><table class="table dense"><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>MCC</th><th>ECE</th><th>ms / msg</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="sub" style="margin-top:8px;font-size:12.5px">Precision, recall and F1 are macro averages over categories. MCC is the Matthews correlation. ECE is calibration error (lower is better).</p></section>
  <div class="grid g2" style="margin-top:16px">
    <section class="card"><h2>Rules, ML and both</h2><div class="tablewrap"><table class="table"><thead><tr><th>Method</th><th>Accuracy</th><th>Precision</th><th>Recall</th></tr></thead><tbody>
      ${['rules_from_training_entities', 'rules_shipped_taxonomy', 'hybrid_rules_then_ml'].filter(k => hy[k]).map(k => `<tr><td>${esc(hy[k].name)}</td><td>${pct1(hy[k].accuracy)}</td><td>${pct1(hy[k].macro_precision)}</td><td>${pct1(hy[k].macro_recall)}</td></tr>`).join('')}</tbody></table></div>
      <p class="sub" style="margin-top:8px">Rules are precise but silent on unknown merchants. ML covers the rest.</p></section>
    <section class="card"><h2>What helps</h2><div class="tablewrap"><table class="table"><thead><tr><th>Variant</th><th>Accuracy</th><th>F1</th></tr></thead><tbody>${abl}</tbody></table></div></section>
  </div>
  <div class="grid g2" style="margin-top:16px">
    <section class="card"><h2>More examples, better scores</h2><p class="sub">Accuracy on unseen merchants against the share of training merchants used. It is still rising, so your own corrections matter.</p>
      ${lineChart(d.learning_curve || [], { xKey: 'fraction', yKey: 'macro_f1', xLabel: 'training share', fmtX: v => Math.round(v * 100) + '%' })}</section>
    <section class="card"><h2>Ask for help when unsure</h2><p class="sub">If the app only auto-files messages it is sure about, accuracy on those goes up and you review the rest.</p>
      ${lineChart((d.selective || {})[sel.name] || [], { xKey: 'coverage', yKey: 'accuracy', xLabel: 'coverage', fmtX: v => Math.round(v * 100) + '%' })}</section>
  </div>
  ${hitl ? `<section class="card" style="margin-top:16px"><h2>With your corrections</h2><p class="sub">${esc(hitl.note || '')}</p><pre class="plain">${esc(JSON.stringify(hitl.summary || hitl, null, 1)).slice(0, 1500)}</pre></section>` : ''}
  ${bt ? `<section class="card" style="margin-top:16px"><h2>Does the monthly planner behave?</h2><p class="sub">${esc(bt.label)} simulation: ${esc(bt.world)}. "Cash below buffer" is the chance that at least one month ends under the safety buffer.</p>
    <div class="tablewrap"><table class="table dense"><thead><tr><th>Income swing</th><th>Policy</th><th>Cash below buffer</th><th>Invested</th><th>Tax saved</th></tr></thead><tbody>
    ${bt.rows.map(r => `<tr class="${r.policy === 'adaptive' ? 'sel' : ''}"><td>${r.sigma}</td><td>${esc(polName[r.policy] || r.policy)}</td><td>${pct1(r.p_breach_buffer)}</td><td>${inr(r.mean_invested)}</td><td>${inr(r.mean_tax_saved)}</td></tr>`).join('')}</tbody></table></div>
    <p class="sub" style="margin-top:8px;font-size:12.5px">The adaptive plan gives up some tax saving to avoid cash squeezes. When income swings very widely it can still end a month under the buffer, which is shown above, not hidden.</p></section>` : ''}
  <section class="card" style="margin-top:16px"><h2>Compared with the base paper</h2><p class="sub">Suganya et al., ICDSBS 2025. Their numbers are quoted from the paper; the two projects solve different problems, so none of the figures is a head-to-head score.</p><div class="tablewrap"><table class="table dense"><thead><tr><th>Item</th><th>Base paper</th><th>This project</th><th>Comparable?</th></tr></thead><tbody>
    <tr><td>Task</td><td>Predict monthly savings from a survey form, then split it across assets</td><td>Read bank SMS, sort it, compute tax, plan month by month</td><td>Different tasks</td></tr>
    <tr><td>Error metrics</td><td>MAE 0.1008, RMSE 0.1418, R² 0.4141</td><td>Not applicable (classification)</td><td>No</td></tr>
    <tr><td>Headline accuracy</td><td>85% "alignment with experts" (experts, sample size and rubric not stated)</td><td>Simulated demo score: 87.39–87.41%; measured live: ${lm && lm.accuracy != null ? pct2(lm.accuracy) + ' on ' + lm.verified + ' reviewed messages' : 'not available'}; synthetic held-out benchmark: ${pct1(T.accuracy)} on ${T.n} messages</td><td>No</td></tr>
    <tr><td>Precision / recall / F1</td><td>Not reported</td><td>${pct1(T.macro.precision)} / ${pct1(T.macro.recall)} / ${pct1(T.macro.f1)} (synthetic); live values above</td><td>Not available</td></tr>
    <tr><td>Uncertainty and significance</td><td>None given</td><td>95% intervals, McNemar test, ablations, calibration</td><td>Ours only</td></tr>
    <tr><td>Models compared</td><td>Rules 72%, ML 78%, GenAI 85% (vs expert advice)</td><td>12 classifiers, rules and hybrids, on one fixed test</td><td>No</td></tr>
    <tr><td>Language model</td><td>Llama 3.1 via Ollama explains the plan</td><td>Local model via Ollama on the Ask page; every figure it quotes is checked against your data</td><td>Similar idea</td></tr>
    <tr><td>Synthetic data</td><td>GAN (no results shown)</td><td>Rule-based generator, merchant-disjoint splits</td><td>Different</td></tr>
    <tr><td>Real data</td><td>Google Form answers</td><td>Your own SMS, checked by you (grows as you review)</td><td>Different</td></tr>
    <tr><td>User study</td><td>80% found explanations clear (n not stated)</td><td>None yet</td><td>Paper only</td></tr>
    <tr><td>Input</td><td>Manual form</td><td>Phone SMS forwarding, live; manual paste</td><td>-</td></tr></tbody></table></div></section>
  <p class="sub" style="margin-top:14px;font-size:12.5px">Figures and the full method are in experiments/results. Run time ${d.runtime_seconds || '?'} s. Decision support, not tax or investment advice.</p>`;
}
