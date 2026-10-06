/* Tax & Cash Co-Pilot - single-page app (no build step) */
const API = location.protocol === 'file:' ? 'http://127.0.0.1:8811' : '';  // served by the backend, so same origin on any port
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inr = n => (n < 0 ? '-' : '') + '₹' + Math.abs(Math.round(n || 0)).toLocaleString('en-IN');
const inrC = n => { const a = Math.abs(n || 0); const s = n < 0 ? '-' : '';
  return a >= 1e7 ? `${s}₹${(a / 1e7).toFixed(2)} Cr` : a >= 1e5 ? `${s}₹${(a / 1e5).toFixed(a >= 1e6 ? 1 : 2)} L` : inr(n); };
const fmtDate = (iso, long) => iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: long === false ? undefined : 'numeric' }) : '';
const daysUntil = iso => Math.ceil((new Date(iso + 'T00:00:00') - new Date(new Date().toDateString())) / 864e5);
const ago = iso => { if (!iso) return 'never'; const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const SECTION_NAME = { '80C': 'Section 80C', '80CCD1B': 'NPS 80CCD(1B)', '80D': 'Health 80D', '24b': 'Home loan 24(b)', '80G': 'Donation 80G', none: '' };
const SECTION_HELP = { '80C': 'ELSS funds, PPF, life insurance, tuition', '80CCD1B': 'Extra NPS contribution', '80D': 'Health insurance and check-ups', '24b': 'Home loan interest' };
const SOURCE = { tier1_taxonomy: ['Matched by rules', 'brand'], tier1_keyword: ['Matched by keywords', 'brand'],
  tier2_ml_fallback: ['Smart guess (AI)', 'blue'], tier2_ml_low_confidence: ['Not sure. Please review', 'warn'], user_correction: ['You set this', 'good'], user_rule: ['Your rule', 'good'],
  user_rule_similar: ['Learned from your fix', 'good'], user_csv_rule: ['Your rules file', 'good'] };

const ICON = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></svg>',
  list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/></svg>',
  tax: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01"/></svg>',
  plan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>',
  info: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  check: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>',
  calc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01"/></svg>',
  more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/></svg>',
  lock: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/></svg>',
};

const PAGES = [
  { id: 'overview', primary: true, label: 'Overview', icon: 'home', title: 'Overview', sub: 'Your money, your tax and what to do next.', render: renderOverview },
  { id: 'transactions', primary: true, label: 'Activity', icon: 'list', title: 'Activity', sub: 'Every bank message, sorted for you automatically.', render: renderTransactions },
  { id: 'tax', label: 'Tax', icon: 'calc', title: 'Your tax', sub: 'Old or new regime, and how much you will owe.', render: renderTax },
  { id: 'monthly', primary: true, label: 'Plan', icon: 'plan', title: 'Monthly plan', sub: 'What is safe to invest each month, after tax and your safety buffer.', render: renderMonthly, after: monthlyAfter },
  { id: 'plan', label: 'Advance tax', icon: 'calc', title: 'Advance tax (quarterly view)', sub: 'The four statutory dates. This is a quarterly view, not the monthly plan.', render: renderPlan },
  { id: 'know', label: 'Know your money', icon: 'info', title: 'Know your money', sub: 'Every money word in this app, explained from zero.', render: renderKnow },
  { id: 'accuracy', label: 'Accuracy', icon: 'check', title: 'How accurate is this app?', sub: 'Measured numbers, and the limits of those numbers.', render: renderAccuracy },
  { id: 'profile', label: 'Profile', icon: 'user', title: 'Profile & income', sub: 'The numbers the planner uses. Keep them up to date.', render: renderProfile },
  { id: 'privacy', label: 'Privacy', icon: 'shield', title: 'Privacy & consent', sub: 'You decide what the app can see.', render: renderPrivacy },
];

/* ---------- plumbing ---------- */
const TK = {
  get() { try { return localStorage.getItem('copilot_token'); } catch (_) { return null; } },
  set(v) { try { localStorage.setItem('copilot_token', v); } catch (_) {} },
  clear() { try { localStorage.removeItem('copilot_token'); } catch (_) {} },
};
async function api(path, opts = {}) {
  let res;
  try {
    const tk = TK.get();
    res = await fetch(API + path, { headers: { 'Content-Type': 'application/json', ...(tk ? { Authorization: 'Bearer ' + tk } : {}) }, ...opts,
      body: opts.body && typeof opts.body !== 'string' ? JSON.stringify(opts.body) : opts.body });
  } catch (e) { $('#offline').hidden = false; throw new Error('Server not reachable'); }
  $('#offline').hidden = true;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith('/auth/')) { TK.clear(); if (typeof showLogin === 'function') showLogin('Please sign in again.'); throw new Error('Please sign in'); }
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === 'string' ? d : d && typeof d.detail === 'string' ? d.detail : Array.isArray(d) ? d.map(x => x.msg).join(', ') : 'Something went wrong');
  }
  return data;
}
function toast(msg, err) {
  const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg;
  $('#toasts').append(t); setTimeout(() => t.remove(), 3600);
}
const skeleton = () => '<div class="grid g2"><div class="sk"></div><div class="sk"></div></div>';

/* ---------- router ---------- */
function buildNav() {
  $('#nav').innerHTML = PAGES.map(p => `<a href="#${p.id}" data-id="${p.id}" class="${p.primary ? 'primary' : ''}">${ICON[p.icon]}<span>${p.label}</span></a>`).join('') +
    `<button type="button" class="more-btn" id="moreBtn" aria-haspopup="dialog" aria-controls="moreSheet">${ICON.more}<span>More</span></button>`;
  $('#moreSheet').innerHTML = `<h2>All sections</h2><div class="more-grid">${PAGES.map(p => `<a href="#${p.id}" data-id="${p.id}">${ICON[p.icon]}<span>${p.title === p.label ? p.label : p.label}</span></a>`).join('')}</div>
    <button class="btn" type="button" data-more-close>Close</button>`;
  $('#moreBtn').onclick = () => { $('#moreSheet').hidden = false; $('#scrim').hidden = false; $('#moreSheet').querySelector('a').focus(); };
}
function closeMore() { $('#moreSheet').hidden = true; if ($('#drawer').hidden) $('#scrim').hidden = true; }
let token = 0;
let authed = false;
async function route() {
  if (!authed) return;
  closeMore();
  const id = (location.hash || '#overview').slice(1).split('?')[0];
  const page = PAGES.find(p => p.id === id) || PAGES[0];
  document.querySelectorAll('#nav a').forEach(a => { if (a.dataset.id === page.id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  $('#pageTitle').textContent = page.title; $('#pageSub').textContent = page.sub;
  document.title = page.title + ' · Tax & Cash Co-Pilot';
  const my = ++token; const view = $('#view'); view.innerHTML = skeleton();
  try { const html = await page.render(view); if (my === token && html !== undefined) view.innerHTML = html; if (my === token && page.after) page.after(view); if (my === token && page.id !== 'know') linkTerms(view); }
  catch (e) { if (my === token) view.innerHTML = `<div class="card empty"><h2>We couldn't load this page</h2><p>${esc(e.message)}</p><button class="btn" onclick="route()">Try again</button></div>`; }
  refreshWho();
}
async function refreshWho() {
  try { const [p, me] = await Promise.all([api('/profile'), api('/me')]);
    $('#who').innerHTML = `<b>${esc(p.name || 'Add your name in Profile')}</b>${esc(me.phone)}`; } catch (_) {}
}

/* ---------- shared pieces ---------- */
function emptyState(msg) {
  return `<div class="card empty"><h2>Let's set you up</h2><p>${msg || 'Add your income and a few bank messages to see your plan.'}</p>
  <button class="btn primary" data-act="demo">Try with demo data</button><button class="btn" data-act="add">Add a bank message</button><a class="btn" href="#profile">Set up profile</a></div>`;
}
function barChart(rows, { h = 150, color = '#0b7a75', avg } = {}) {
  if (!rows.length) return '<p class="sub">No income recorded yet.</p>';
  const w = 560, pad = 26, max = Math.max(...rows.map(r => r.v), 1) * 1.12, bw = Math.min(34, (w - pad) / rows.length - 8);
  const step = (w - pad) / rows.length, y = v => h - 22 - (v / max) * (h - 34);
  const bars = rows.map((r, i) => { const x = pad + i * step + (step - bw) / 2;
    return `<rect x="${x}" y="${y(r.v)}" width="${bw}" height="${h - 22 - y(r.v)}" rx="6" fill="${color}"><title>${esc(r.l)}: ${inr(r.v)}</title></rect>
    <text x="${x + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(r.l)}</text>`; }).join('');
  const line = avg ? `<line x1="${pad - 6}" x2="${w}" y1="${y(avg)}" y2="${y(avg)}" stroke="#f0a93b" stroke-width="2" stroke-dasharray="5 5"/>` : '';
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Monthly income chart">${bars}${line}</svg>` +
    (avg ? `<p class="sub" style="font-size:13px;margin-top:8px"><span class="dot" style="background:#f0a93b;width:18px;height:3px;border-radius:2px;vertical-align:middle"></span> Average ${inr(avg)} a month</p>` : '');
}
function monthLabel(m) { return new Date(m + '-01T00:00:00').toLocaleDateString('en-IN', { month: 'short' }); }
const field = (id, label, val, { prefix, type = 'number', help, step } = {}) => `<div class="field"><label for="${id}">${label}</label>
  ${prefix ? `<div class="money"><span>${prefix}</span><input class="input" id="${id}" type="${type}" inputmode="decimal" min="0" ${step ? `step="${step}"` : ''} value="${esc(val)}"></div>` : `<input class="input" id="${id}" type="${type}" value="${esc(val)}">`}
  ${help ? `<small>${help}</small>` : ''}</div>`;

/* ---------- Overview ---------- */
async function renderOverview() {
  const [d, tx, inc] = await Promise.all([api('/dashboard'), api('/transactions?limit=6'), api('/income')]);
  if (!d.has_income && !tx.length) return emptyState();
  const L = d.liquidity, T = d.tax, bal = Math.max(L.balance, 1);
  const buf = Math.min(L.safety_buffer, Math.max(L.balance, 0)), res = Math.min(L.advance_tax_reserve, Math.max(L.balance - buf, 0));
  const inv = Math.max(L.balance - buf - res, 0);
  const pct = v => Math.max((v / bal) * 100, v > 0 ? 1.5 : 0).toFixed(1);
  const days = L.next_advance_tax_due ? daysUntil(L.next_advance_tax_due) : null;
  const paidPct = T.estimated_tax ? Math.min(100, T.paid_so_far / T.estimated_tax * 100) : 0;
  const incRows = inc.slice(-12).map(r => ({ l: monthLabel(r.month), v: r.amount }));
  const avg = incRows.length ? incRows.reduce((a, r) => a + r.v, 0) / incRows.length : 0;
  const newBest = T.recommended_regime === 'new';
  const score = d.tax_drag.efficiency_score;
  return `
  <div class="grid g-hero">
    <section class="card hero">
      <div class="lbl">Safe to invest right now</div>
      <div class="big">${inr(L.investable_now)}</div>
      <p class="say">${esc(d.tip)}</p>
      <div class="split" role="img" aria-label="How your balance is split">
        <i style="width:${pct(buf)}%;background:#6fb7e8"></i><i style="width:${pct(res)}%;background:#f0a93b"></i><i style="width:${pct(inv)}%;background:#4fd6a8"></i></div>
      <div class="legend">
        <div><span class="dot" style="background:#6fb7e8"></span>Safety buffer <b>${inr(buf)}</b></div>
        <div><span class="dot" style="background:#f0a93b"></span>Set aside for tax <b>${inr(res)}</b></div>
        <div><span class="dot" style="background:#4fd6a8"></span>Free to invest <b>${inr(inv)}</b></div>
      </div>
      <p class="say" style="margin-top:14px;font-size:13.5px">Your balance is ${inr(L.balance)}, enough for ${L.runway_months ?? 0} months of spending.</p>
    </section>
    <section class="card">
      <div class="card-head"><h2>Tax for ${esc(d.fy)}</h2><span class="chip ${newBest ? 'brand' : 'gold'}">${newBest ? 'New' : 'Old'} regime is better</span></div>
      <div class="stat"><div class="val" style="font-size:34px;margin-top:0">${inr(T.estimated_tax)}</div>
        <div class="note">${T.effective_rate}% of your income of ${inrC(d.annual_income)}</div></div>
      <div style="margin:18px 0 6px" class="bar gold"><i style="width:${paidPct}%"></i></div>
      <div class="note" style="display:flex;justify-content:space-between;color:var(--ink-2);font-size:13.5px"><span>Paid ${inr(T.paid_so_far)}</span><span>Still to pay ${inr(T.remaining)}</span></div>
      <p class="sub" style="margin-top:14px">The other regime would cost ${inr(newBest ? T.old : T.new)}.</p>
      <a class="btn small" style="margin-top:12px" href="#tax">See how it's worked out</a>
    </section>
  </div>

  <div class="grid g3" style="margin-top:18px">
    <section class="card stat"><div class="lbl">Next advance tax</div>
      <div class="val">${L.next_advance_tax_due ? fmtDate(L.next_advance_tax_due, false) : 'None due'}</div>
      <div class="note">${days !== null ? (days >= 0 ? `In ${days} day${days === 1 ? '' : 's'}` : 'Past due') : ''}${L.advance_tax_reserve ? ` · set aside ${inr(L.advance_tax_reserve)}` : ''}</div></section>
    <section class="card stat"><div class="lbl">Last 30 days</div>
      <div class="val" style="color:var(--good)">+${inrC(d.last_30_days.received)}</div>
      <div class="note">${inr(d.last_30_days.spent)} spent</div></section>
    <section class="card stat"><div class="lbl">Tax health</div>
      <div class="val">${score}<span style="font-size:16px;color:var(--ink-3)"> / 100</span></div>
      <div class="note">${d.tax_drag.avoidable_tax > 0 ? `${inr(d.tax_drag.avoidable_tax)} of tax you can still avoid` : 'No avoidable tax found'}</div></section>
  </div>

  <div class="grid g2" style="margin-top:18px">
    <section class="card"><div class="card-head"><h2>Tax-saving room</h2><a href="#monthly" class="chip brand" style="text-decoration:none">See monthly plan</a></div>
      ${d.sections.map(s => `<div class="row-bar"><div class="top"><b>${SECTION_NAME[s.section]}</b><span>${inr(s.used)} of ${inr(s.cap)}</span></div>
        <div class="bar"><i style="width:${Math.min(100, s.pct_used)}%"></i></div><span class="sub" style="font-size:12.5px;color:var(--ink-3)">${SECTION_HELP[s.section]} · ${inr(s.headroom)} left</span></div>`).join('')}
      ${newBest ? `<div class="callout brand" style="margin-top:14px">${ICON.info}<span>These deductions only count in the old regime. Right now the new regime gives you a lower bill, so extra investing won't reduce your tax.</span></div>` : ''}
    </section>
    <section class="card"><div class="card-head"><h2>Monthly income</h2><a href="#profile" class="chip" style="text-decoration:none">Edit</a></div>
      ${barChart(incRows, { avg, h: 230 })}</section>
  </div>

  <section class="card" style="margin-top:18px"><div class="card-head"><h2>Recent activity</h2><a href="#transactions" class="chip brand" style="text-decoration:none">See all</a></div>
    <div class="list">${tx.map(txRow).join('') || '<p class="sub">Nothing here yet.</p>'}</div></section>`;
}

/* ---------- Activity ---------- */
function txRow(t) {
  const credit = t.type === 'credit', taxy = t.tax_section !== 'none';
  const ini = esc((t.merchant || t.label || '?').replace(/[^A-Za-z0-9 ]/g, '').split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?');
  return `<button class="item" data-tx="${t.id}"><div class="ico ${credit ? 'in' : taxy ? 'tax' : 'out'}">${ini}</div>
    <div><div class="m">${esc(t.merchant || 'Unknown')}</div><div class="s"><span>${esc(t.label)}</span>${taxy ? `<span class="chip gold">${SECTION_NAME[t.tax_section]}</span>` : ''}${t.source === 'tier2_ml_low_confidence' ? '<span class="chip warn">Review</span>' : ''}</div></div>
    <div class="amt ${credit ? 'in' : ''}">${credit ? '+' : '-'}${inr(t.amount)}<small>${fmtDate(t.date)}</small></div></button>`;
}
let txAll = [], txFilter = 'all', txQuery = '';
async function renderTransactions() {
  txAll = await api('/transactions?limit=1000');
  if (!txAll.length) return emptyState('No bank messages yet. Paste one to see how it is read and sorted.');
  return `<section class="card"><div class="toolbar"><div class="tabs" id="txTabs">
    ${[['all', 'All'], ['credit', 'Money in'], ['debit', 'Money out'], ['tax', 'Tax-saving']].map(([k, l]) => `<button class="tab" data-f="${k}" aria-pressed="${k === txFilter}">${l}</button>`).join('')}</div>
    <input class="input" id="txSearch" type="search" placeholder="Search merchant or category" aria-label="Search activity" value="${esc(txQuery)}"></div>
    <div class="list" id="txList"></div></section>
    <section class="card" id="rulesCard" style="margin-top:18px"></section>`;
}
renderTransactions.after = async view => { paintTx();
  try { const r = await api('/rules'); const L = r.learned_from_you;
    $('#rulesCard').innerHTML = `<div class="card-head"><div><h2>What the app learned from you</h2><p class="sub">Each time you fix a category, the merchant is remembered. You can also edit <code>${esc(r.files.rules_csv)}</code> in a spreadsheet.</p></div></div>
      <div class="tablewrap"><table class="table"><thead><tr><th>Merchant</th><th>Category</th><th>Used</th><th></th></tr></thead><tbody>${L.map(x => `<tr><td>${esc(x.merchant)}</td><td>${esc(x.category.replace(/_/g, ' '))}</td><td>${x.used}</td><td style="text-align:right"><button class="btn small" data-delrule="${x.id}">Forget</button></td></tr>`).join('') || '<tr><td colspan="4">Nothing yet. Open a transaction and correct its category.</td></tr>'}</tbody></table></div>`; } catch (_) {} };
function paintTx() {
  const el = $('#txList'); if (!el) return;
  const q = txQuery.toLowerCase();
  const rows = txAll.filter(t => (txFilter === 'all' || (txFilter === 'tax' ? t.tax_section !== 'none' : t.type === txFilter)) &&
    (!q || (t.merchant + ' ' + t.label + ' ' + t.category).toLowerCase().includes(q)));
  el.innerHTML = rows.map(txRow).join('') || '<p class="sub" style="padding:14px 4px">No matches. Try another filter.</p>';
}
PAGES.find(p => p.id === 'transactions').after = renderTransactions.after;

let CATS = null;
async function loadCats() { if (!CATS) CATS = await api('/categories'); return CATS; }
async function openDrawer(id) {
  const dr = $('#drawer'); $('#scrim').hidden = false; dr.hidden = false; dr.innerHTML = '<div class="sk"></div>';
  try {
    const [t, raw, ex] = await Promise.all([api(`/transactions/${id}`), api(`/transactions/${id}/raw`), api(`/transactions/${id}/explain`), loadCats()]);
    const credit = t.type === 'credit', e = ex.explanation, src = SOURCE[t.source] || [t.source, ''];
    dr.innerHTML = `<button class="btn small close" data-close>Close</button>
      <span class="chip ${credit ? 'good' : ''}">${credit ? 'Money in' : 'Money out'}</span>
      <h2>${esc(t.merchant || 'Unknown')}</h2>
      <div style="font:700 30px var(--display);letter-spacing:-.02em;margin:4px 0 14px;color:${credit ? 'var(--good)' : 'var(--ink)'}">${credit ? '+' : '-'}${inr(t.amount)}</div>
      <div class="kv"><div><span>Date</span><b>${fmtDate(t.date)}</b></div><div><span>Sorted as</span><b>${esc(t.label)}</b></div>
        <div><span>Tax section</span><b>${t.tax_section === 'none' ? 'None' : esc(SECTION_NAME[t.tax_section])}</b></div>
        <div><span>How we decided</span><span class="chip ${src[1]}">${src[0]}${t.source.startsWith('tier2') ? ` · ${Math.round(t.confidence * 100)}% sure` : ''}</span></div>
        <div><span>Account</span><b>${t.account ? '••' + esc(t.account) : '-'}</b></div></div>
      ${t.user_corrected || t.confirmed ? `<div class="callout good" style="margin-bottom:10px">${ICON.check}<span>You checked this one. It counts toward your real-world accuracy.</span></div>`
        : `<div class="callout brand" style="margin-bottom:10px;align-items:center">${ICON.info}<span style="flex:1">Is <b>${esc(t.label)}</b> right?</span><button class="btn small primary" data-confirm="${t.id}">Looks right</button></div>`}
      <div class="fix"><label for="fixCat">Wrong category? Change it</label>
        <select class="input" id="fixCat">${CATS.filter(c => c.direction === t.type).map(c => `<option value="${c.id}" ${c.id === t.category ? 'selected' : ''}>${esc(c.label)}${c.tax_section !== 'none' ? ' (' + esc(SECTION_NAME[c.tax_section] || c.tax_section) + ')' : ''}</option>`).join('')}</select>
        <label class="check"><input type="checkbox" id="fixSim" checked> Apply to similar messages and remember this merchant</label>
        <button class="btn small" data-fix="${t.id}">Save category</button></div>
      <h3 style="margin:22px 0 8px;font:700 15px var(--display)">${esc(e.title)}</h3>
      <p class="sub" style="color:var(--ink-2)">${esc(e.summary)}</p><p style="margin-top:8px"><b>Limit:</b> ${esc(e.limit)}</p>
      <h3 style="margin:22px 0 8px;font:700 15px var(--display)">Original message</h3>
      <div class="sms">${esc(raw.raw_sms)}</div>
      <div class="lock" style="margin-top:12px">${ICON.lock} Stored encrypted on this device. What's saved looks like this:<span class="mono">${esc(raw.stored_as_ciphertext)}</span></div>
      <button class="btn danger small" style="margin-top:20px" data-del="${t.id}">Delete this transaction</button>`;
    dr.querySelector('[data-close]').focus();
  } catch (e) { dr.innerHTML = `<button class="btn small close" data-close>Close</button><p style="margin-top:30px">${esc(e.message)}</p>`; }
}
function closeDrawer() { $('#drawer').hidden = true; $('#scrim').hidden = true; }

/* ---------- Add transaction ---------- */
function openAdd() {
  const d = new Date(), ds = `${String(d.getDate()).padStart(2, '0')}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getFullYear()).slice(2)}`;
  const samples = [
    ['Food order', `Rs.2,450.00 debited from A/c XX4821 on ${ds} to VPA zomato@ybl (UPI Ref 481726). Bal Rs 1,48,200.00`],
    ['Client payment', `INR 85,000.00 credited to A/c XX4821 on ${ds} by UPWORK ESCROW. Avl Bal INR 2,33,200.00`],
    ['Tax-saving fund', `Rs 15,000 debited from A/c XX4821 on ${ds} to AXIS LONG TERM EQUITY FUND. Bal Rs 1,33,200`],
    ['Health check-up', `Rs 4,500 debited from A/c XX4821 on ${ds} to APEX FULL BODY CHECKUP. Bal Rs 1,28,700`]];
  const dlg = $('#addDlg');
  dlg.innerHTML = `<form method="dialog" id="addForm"><h2 id="addTitle">Add a bank message</h2>
    <p class="sub" style="color:var(--ink-2)">Paste the SMS from your bank. We read the amount, who it went to and which tax section it fits.</p>
    <div class="samples">${samples.map((s, i) => `<button type="button" class="sample" data-s="${i}">${s[0]}</button>`).join('')}</div>
    <div class="field"><label for="smsText">Message</label><textarea class="input" id="smsText" placeholder="Rs.1,250.00 debited from A/c XX1234 on 12-09-26 to VPA swiggy@ybl..." required></textarea></div>
    <div id="addResult"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px"><button class="btn" type="button" data-dlgclose>Close</button><button class="btn primary" id="addSubmit" type="submit">Read message</button></div></form>`;
  dlg.showModal();
  dlg.querySelectorAll('.sample').forEach(b => b.onclick = () => { $('#smsText').value = samples[b.dataset.s][1]; $('#smsText').focus(); });
  dlg.querySelector('[data-dlgclose]').onclick = () => dlg.close();
  $('#addForm').onsubmit = async ev => {
    ev.preventDefault(); const btn = $('#addSubmit'); btn.disabled = true; btn.textContent = 'Reading…';
    try {
      const t = await api('/sms/ingest', { method: 'POST', body: { text: $('#smsText').value } });
      const src = SOURCE[t.source] || [t.source, ''];
      $('#addResult').innerHTML = `<div class="result"><div style="display:flex;justify-content:space-between;gap:12px"><b>${esc(t.merchant || 'Unknown')}</b><b style="color:${t.type === 'credit' ? 'var(--good)' : 'inherit'}">${t.type === 'credit' ? '+' : '-'}${inr(t.amount)}</b></div>
        <div class="s" style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap"><span class="chip">${esc(t.label)}</span>${t.tax_section !== 'none' ? `<span class="chip gold">${SECTION_NAME[t.tax_section]}</span>` : ''}<span class="chip ${src[1]}">${src[0]}</span></div></div>`;
      toast('Transaction added'); $('#smsText').value = ''; route();
    } catch (e) { $('#addResult').innerHTML = `<div class="callout bad" style="margin-top:14px">${ICON.info}<span>${esc(e.message)}. Check that it mentions an amount and says debited or credited.</span></div>`; }
    btn.disabled = false; btn.textContent = 'Read message';
  };
}

/* ---------- Tax ---------- */
function regimeCard(r, win, name, tagline) {
  const rows = [['Your income', inr(r.gross)], ['Standard deduction', '-' + inr(r.standard_deduction)],
    ...(name === 'Old' ? [['Other deductions', '-' + inr(r.deductions_total)]] : []),
    ['Taxable income', inr(r.taxable_income)], ['Tax on slabs', inr(r.slab_tax)], ['Rebate (87A)', '-' + inr(r.rebate_87a)], ['Cess (4%)', inr(r.cess)]];
  return `<section class="card regime ${win ? 'win' : ''}">${win ? '<span class="chip brand badge">Better for you</span>' : ''}
    <h2>${name} regime</h2><p class="sub">${tagline}</p><div class="total">${inr(r.total_tax)}</div><span class="sub">${r.effective_rate}% of your income</span>
    <div class="kv">${rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('')}</div></section>`;
}
async function renderTax() {
  const [r, p] = await Promise.all([api('/simulate/regime'), api('/profile')]);
  if (!r.annual_income) return emptyState('Add your annual income first so we can work out your tax.');
  const win = r.recommended, haveDed = r.old_deductions_total, be = r.breakeven_deductions;
  const beNote = be === null ? 'The old regime would not win at this income.' : be === 0 ? 'The old regime already wins for you.' :
    `The old regime would only win if your deductions reached ${inr(be)}. You have ${inr(r.old.deductions_total)} so far.`;
  const q = x => Math.round(x || 0);
  const du = r.deductions_used;
  return `<div class="callout ${win === 'new' ? 'brand' : 'good'}" style="margin-bottom:18px">${ICON.check}<span><b>${win === 'new' ? 'New' : 'Old'} regime saves you ${inr(r.saving_by_choosing)}</b> for ${esc(r.fy)}. Based on ${esc(r.income_source === 'profile' ? 'the income in your profile' : 'your average monthly income × 12')}.</span></div>
  <div class="grid g2">${regimeCard(r.new, win === 'new', 'New', 'Lower rates, almost no deductions')}${regimeCard(r.old, win === 'old', 'Old', 'Higher rates, but deductions count')}</div>
  <section class="card" style="margin-top:18px"><h2>Could the old regime ever win?</h2><p class="sub">${beNote}</p>
    <div class="bar" style="margin-top:14px"><i style="width:${be ? Math.min(100, r.old.deductions_total / be * 100) : 100}%"></i></div></section>
  <section class="card" style="margin-top:18px"><div class="card-head"><div><h2>Try your own numbers</h2><p class="sub">Change income or investments and see the result right away. Nothing is saved.</p></div></div>
    <div class="form-grid">
      ${field('wi_income', 'Yearly income', q(r.annual_income), { prefix: '₹' })}
      <div class="field"><label>Type of income</label><div class="seg" id="wi_type"><button type="button" data-v="1" aria-pressed="${p.income_type === 'salaried'}">Salaried</button><button type="button" data-v="0" aria-pressed="${p.income_type !== 'salaried'}">Self-employed</button></div></div>
      ${field('wi_80C', 'Section 80C (limit ₹1,50,000)', q(du['80C']), { prefix: '₹' })}
      ${field('wi_80CCD1B', 'NPS 80CCD(1B) (limit ₹50,000)', q(du['80CCD1B']), { prefix: '₹' })}
      ${field('wi_80D', 'Health insurance 80D (limit ₹25,000)', q(du['80D']), { prefix: '₹' })}
      ${field('wi_24b', 'Home loan interest (limit ₹2,00,000)', q(du['24b']), { prefix: '₹' })}
    </div><div id="wi_out" style="margin-top:18px"></div></section>`;
}
PAGES.find(p => p.id === 'tax').after = () => {
  if (!$('#wi_income')) return;
  const run = async () => {
    const n = id => +($('#' + id).value || 0);
    try {
      const out = await api('/simulate/what_if', { method: 'POST', body: { annual_income: Math.max(n('wi_income'), 1), age: 30,
        salaried: $('#wi_type [aria-pressed="true"]').dataset.v === '1', d80C: n('wi_80C'), d80CCD1B: n('wi_80CCD1B'), d80D: n('wi_80D'), d24b: n('wi_24b') } });
      const w = out.recommended;
      $('#wi_out').innerHTML = `<div class="grid g3"><div class="card stat" style="box-shadow:none"><div class="lbl">New regime</div><div class="val">${inr(out.new.total_tax)}</div></div>
        <div class="card stat" style="box-shadow:none"><div class="lbl">Old regime</div><div class="val">${inr(out.old.total_tax)}</div></div>
        <div class="callout ${w === 'new' ? 'brand' : 'good'}">${ICON.check}<span><b>${w === 'new' ? 'New' : 'Old'} regime</b> is cheaper by ${inr(out.saving_by_choosing)}.</span></div></div>`;
    } catch (e) { $('#wi_out').innerHTML = `<p class="sub">${esc(e.message)}</p>`; }
  };
  const d = debounce(run, 300);
  document.querySelectorAll('[id^=wi_]').forEach(i => i.tagName === 'INPUT' && i.addEventListener('input', d));
  document.querySelectorAll('#wi_type button').forEach(b => b.onclick = () => { document.querySelectorAll('#wi_type button').forEach(x => x.setAttribute('aria-pressed', x === b)); run(); });
  run();
};

/* ---------- Plan ---------- */
async function renderPlan() {
  const m = await api('/dashboard/multi_period');
  if (!m.periods.length) return emptyState(m.message);
  const pay = m.periods.reduce((a, p) => a + p.advance_tax_due, 0);
  const planHtml = m.periods.map(p => {
    const d = daysUntil(p.due_date);
    const inv = Object.entries(p.invest).filter(([, v]) => v > 0);
    const acts = [];
    if (p.advance_tax_due > 0) acts.push(`<div class="act pay"><div><b>Pay advance tax</b><small>Keep this ready by ${fmtDate(p.due_date)}</small></div><b>${inr(p.advance_tax_due)}</b></div>`);
    inv.forEach(([s, v]) => acts.push(`<div class="act inv"><div><b>Invest in ${SECTION_NAME[s]}</b><small>${SECTION_HELP[s]}</small></div><b>${inr(v)}</b></div>`));
    if (!acts.length) acts.push('<div class="act"><div><b>Nothing to do</b><small>No advance tax or investing needed in this period</small></div></div>');
    return `<div class="qcard"><div class="when"><b>${esc(p.quarter)}</b><span>${fmtDate(p.due_date)}</span><br><span>${d >= 0 ? `in ${d} days` : 'passed'}</span></div>
      <div class="acts">${acts.join('')}<div class="sub" style="font-size:13.5px;color:${p.liquidity_ok ? 'var(--ink-2)' : 'var(--bad)'}">${p.liquidity_ok ? 'Cash stays healthy' : 'Cash gets tight'}: ${inr(p.cash_at_quantile)} left in a ${Math.round(m.alpha * 100)}% cautious case (buffer ${inr(p.buffer_required)})</div></div></div>`;
  }).join('');
  const w = 560, h = 170, max = Math.max(...m.periods.map(p => Math.max(p.cash_at_quantile, p.buffer_required)), 1) * 1.15, bw = 54, step = (w - 30) / m.periods.length;
  const yv = v => h - 24 - (Math.max(v, 0) / max) * (h - 40);
  const bars = m.periods.map((p, i) => { const x = 30 + i * step + (step - bw) / 2;
    return `<rect x="${x}" y="${yv(p.cash_at_quantile)}" width="${bw}" height="${h - 24 - yv(p.cash_at_quantile)}" rx="8" fill="${p.liquidity_ok ? '#0b7a75' : '#d04545'}"><title>${inr(p.cash_at_quantile)}</title></rect>
      <text x="${x + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(p.quarter)}</text><text x="${x + bw / 2}" y="${yv(p.cash_at_quantile) - 6}" text-anchor="middle">${inrC(p.cash_at_quantile)}</text>`; }).join('');
  const by = yv(m.buffer);
  return `<div class="callout ${m.feasible ? 'brand' : 'bad'}" style="margin-bottom:18px">${ICON.info}<span>${esc(m.message || '')}</span></div>
  <div class="grid g3"><section class="card stat"><div class="lbl">Tax before plan</div><div class="val">${inr(m.tax_before)}</div></section>
    <section class="card stat"><div class="lbl">Tax after plan</div><div class="val">${inr(m.tax_after)}</div><div class="note">${m.tax_saved > 0 ? `You save ${inr(m.tax_saved)}` : 'No change'}</div></section>
    <section class="card stat"><div class="lbl">Advance tax to set aside</div><div class="val">${inr(pay)}</div><div class="note">Across the remaining dates</div></section></div>
  <h2 style="font:700 18px var(--display);margin:26px 0 12px">What to do, date by date</h2><div class="timeline">${planHtml}</div>
  <section class="card" style="margin-top:18px"><div class="card-head"><div><h2>Cash after each date</h2><p class="sub">Dashed line is your safety buffer.</p></div></div>
    <svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Cash after each tax date">${bars}<line x1="24" x2="${w}" y1="${by}" y2="${by}" stroke="#f0a93b" stroke-width="2" stroke-dasharray="6 5"/><text x="${w}" y="${by - 6}" text-anchor="end">buffer ${inrC(m.buffer)}</text></svg></section>
  <section class="card" style="margin-top:18px"><h2>What if you had invested earlier?</h2><p class="sub">Money invested sooner has longer to grow.</p>
    <div class="form-grid" style="margin-top:14px">${field('cf_amt', 'Amount', 50000, { prefix: '₹' })}${field('cf_days', 'Days earlier', 90)}</div>
    <div id="cf_out" class="callout gold" style="margin-top:16px">${ICON.info}<span>…</span></div></section>
  <p class="sub" style="margin-top:16px;font-size:12.5px">How this is worked out: your monthly income is modelled from your history (${m.income_model.source === 'fitted' ? m.income_model.samples + ' months' : 'estimated, as there is little history'}), and we plan for a ${Math.round(m.alpha * 100)}% cautious case so you can still cover your buffer. This is decision support, not tax advice.</p>`;
}
PAGES.find(p => p.id === 'plan').after = () => {
  if (!$('#cf_amt')) return;
  const run = async () => { try { const r = await api(`/simulate/counterfactual?amount=${+$('#cf_amt').value || 0}&days_earlier=${+$('#cf_days').value || 0}`);
    $('#cf_out span').textContent = r.message; } catch (e) { $('#cf_out span').textContent = e.message; } };
  const d = debounce(run, 300); $('#cf_amt').oninput = d; $('#cf_days').oninput = d; run();
};

/* ---------- Profile ---------- */
async function renderProfile() {
  const [p, inc] = await Promise.all([api('/profile'), api('/income')]);
  const months = inc.slice(-12);
  return `<div class="grid g2">
  <section class="card"><h2>About you</h2><p class="sub">These drive your tax and cash plan.</p><form id="profForm" class="form-grid" style="margin-top:16px">
    <div class="field full"><label for="p_name">Name</label><input class="input" id="p_name" value="${esc(p.name)}"></div>
    <div class="field full"><label>How do you earn?</label><div class="seg" id="p_type"><button type="button" data-v="salaried" aria-pressed="${p.income_type === 'salaried'}">Salaried</button><button type="button" data-v="freelancer" aria-pressed="${p.income_type !== 'salaried'}">Freelancer or self-employed</button></div></div>
    ${field('p_income', 'Yearly income', Math.round(p.annual_income), { prefix: '₹', help: 'Enter 0 to estimate from your monthly income. Self-employed: use income after business costs.' })}
    ${field('p_exp', 'Monthly spending', Math.round(p.monthly_expenses), { prefix: '₹' })}
    ${field('p_bal', 'Bank balance', Math.round(p.current_balance), { prefix: '₹', help: 'Updates by itself when a message shows your balance.' })}
    ${field('p_buf', 'Safety buffer (months of spending)', p.safety_buffer_months, { step: '0.5' })}
    ${field('p_age', 'Age', p.age)}
    ${field('p_loan', 'Home loan interest per year', Math.round(p.home_loan_interest), { prefix: '₹' })}
    <div class="field full"><label for="p_job">Work / role</label><input class="input" id="p_job" value="${esc(p.occupation || '')}"></div>
    ${field('p_sal', 'Monthly salary or income', Math.round(p.monthly_salary || 0), { prefix: '₹' })}
    ${field('p_fd', 'Other savings (FD, RD, cash)', Math.round(p.savings_other || 0), { prefix: '₹' })}
    ${field('p_emi', 'Loan EMI per month', Math.round(p.loan_emi || 0), { prefix: '₹' })}
    ${field('p_lout', 'Loan still owed', Math.round(p.loan_outstanding || 0), { prefix: '₹' })}
    ${field('p_inv', 'Investments, current value', Math.round(p.investments_value || 0), { prefix: '₹' })}
    ${field('p_other', 'Other old-regime deductions per year', Math.round(p.other_deductions_old || 0), { prefix: '₹', help: 'HRA, LTA, employer NPS and similar, worked out by you or your employer. Only used if the old regime is cheaper.' })}
    ${field('p_paid', 'Tax already paid this year', Math.round(p.tax_paid_so_far), { prefix: '₹', help: 'Advance tax plus tax deducted at source.' })}
    <div class="field"><label for="p_alpha">How cautious should we be?</label><select class="input" id="p_alpha">${[[0.8, 'Relaxed (80%)'], [0.9, 'Balanced (90%)'], [0.95, 'Careful (95%)'], [0.99, 'Very careful (99%)']].map(([v, l]) => `<option value="${v}" ${Math.abs(p.risk_alpha - v) < 0.001 ? 'selected' : ''}>${l}</option>`).join('')}</select><small>Higher means we keep more cash spare in a bad month.</small></div>
    <div class="full"><button class="btn primary" type="submit">Save profile</button></div></form></section>
  <section class="card"><h2>Monthly income</h2><p class="sub">The last 12 months help us judge how steady your income is.</p>
    <div style="margin:14px 0">${barChart(months.map(r => ({ l: monthLabel(r.month), v: r.amount })))}</div>
    <form id="incForm" class="form-grid"><div class="field"><label for="i_month">Month</label><input class="input" id="i_month" type="month" required></div>${field('i_amt', 'Income received', '', { prefix: '₹' })}
      <div class="full"><button class="btn" type="submit">Add or update month</button></div></form>
    <table class="table" style="margin-top:12px"><tbody>${[...inc].reverse().slice(0, 12).map(r => `<tr><td>${new Date(r.month + '-01T00:00:00').toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</td><td style="text-align:right"><b>${inr(r.amount)}</b></td><td style="text-align:right"><button class="btn small" data-delinc="${r.month}" aria-label="Remove ${r.month}">Remove</button></td></tr>`).join('') || '<tr><td>No months added yet.</td></tr>'}</tbody></table></section></div>`;
}
PAGES.find(p => p.id === 'profile').after = () => {
  const f = $('#profForm'); if (!f) return;
  document.querySelectorAll('#p_type button').forEach(b => b.onclick = () => document.querySelectorAll('#p_type button').forEach(x => x.setAttribute('aria-pressed', x === b)));
  f.onsubmit = async e => { e.preventDefault(); const n = id => +($('#' + id).value || 0);
    try { await api('/profile', { method: 'PUT', body: { name: $('#p_name').value, income_type: $('#p_type [aria-pressed="true"]').dataset.v, annual_income: n('p_income'),
      monthly_expenses: n('p_exp'), current_balance: n('p_bal'), safety_buffer_months: n('p_buf'), age: n('p_age'), home_loan_interest: n('p_loan'), tax_paid_so_far: n('p_paid'), other_deductions_old: n('p_other'), occupation: $('#p_job').value, monthly_salary: n('p_sal'), savings_other: n('p_fd'), loan_emi: n('p_emi'), loan_outstanding: n('p_lout'), investments_value: n('p_inv'), risk_alpha: +$('#p_alpha').value } });
      toast('Profile saved'); refreshWho(); } catch (err) { toast(err.message, true); } };
  $('#incForm').onsubmit = async e => { e.preventDefault();
    try { await api('/income', { method: 'POST', body: { month: $('#i_month').value, amount: +$('#i_amt').value } }); toast('Income saved'); route(); } catch (err) { toast(err.message, true); } };
};

/* ---------- Privacy ---------- */
async function renderPrivacy() {
  const [cons, ev, sys, me] = await Promise.all([api('/consent'), api('/events/recent?n=8'), api('/system'), api('/me')]);
  const stat = { ACTIVE: 'good', REVOKED: 'bad', EXPIRED: 'warn' };
  return `<div class="grid g2"><section class="card"><div class="card-head"><div><h2>Data access consent</h2><p class="sub">Choose when the app may read your bank data. You can take it back at any time.</p></div></div>
    <button class="btn primary" id="grantBtn">Give consent for 90 days</button>
    <div class="list" style="margin-top:16px">${cons.map(c => `<div class="item" style="cursor:default;grid-template-columns:1fr auto"><div><div class="m">${esc(c.consentHandle)}</div><div class="s"><span>${esc(c.purpose.text)}</span><span>Until ${fmtDate((c.consentExpiry || '').slice(0, 10))}</span></div></div>
      <div style="display:grid;gap:6px;justify-items:end"><span class="chip ${stat[c.status] || ''}">${c.status === 'ACTIVE' ? 'Active' : c.status === 'REVOKED' ? 'Withdrawn' : 'Expired'}</span>${c.status === 'ACTIVE' ? `<button class="btn small" data-revoke="${c.id}">Withdraw</button>` : ''}</div></div>`).join('') || '<p class="sub">No consent given yet.</p>'}</div>
    <p class="sub" style="margin-top:14px;font-size:12.5px">This shows how an Account Aggregator consent works. It is not connected to a live aggregator.</p></section>
  <section class="card"><h2>How we protect your data</h2><div class="stack" style="margin-top:14px">
    <div class="callout brand">${ICON.lock}<span><b>Messages are encrypted.</b> The original text of every SMS is locked with a key on this device before it is saved.</span></div>
    <div class="callout brand">${ICON.lock}<span><b>Your account is private.</b> You sign in with a code sent to your phone number. Every record is tied to your account and the server never returns another person's data.</span></div>
    <div class="callout ${me.phone_connected ? 'brand' : 'gold'}">${ICON.shield}<span><b>Phone SMS feed:</b> ${me.phone_connected ? 'connected, last message ' + esc(ago(me.last_sms_at)) + '.' : 'not connected yet.'} Your phone sends messages with a key that belongs only to you. <a href="#connect">Open Connect phone</a>.</span></div>
    <div class="callout ${sys.llm.available ? 'brand' : 'gold'}">${ICON.info}<span><b>Assistant:</b> ${sys.llm.available ? 'answers are written by the local model ' + esc(sys.llm.model) + ' on this computer. Your data is not sent anywhere.' : 'no local AI model found, so answers use fixed rules.'}</span></div>
    <div class="callout brand">${ICON.info}<span><b>Encryption key:</b> ${esc(sys.encryption_key_source)}. Backups kept: ${sys.backups}${sys.latest_backup ? ' (latest ' + esc(sys.latest_backup) + ')' : ''}. Tax rules last checked ${esc(sys.tax_rules.last_verified)}.</span></div>
    <div class="callout brand">${ICON.shield}<span><b>Only coarse signals are shared.</b> Events carry a category and an amount range, never the shop name or exact amount.</span></div></div>
    <h3 style="font:700 15px var(--display);margin:20px 0 6px">Latest shared signals</h3>
    <table class="table"><thead><tr><th>Event</th><th>Category</th><th>Range</th></tr></thead><tbody>${ev.map(e => `<tr><td>${esc(e.topic.replace('txn.classified', 'transaction').replace('consent.', 'consent '))}</td><td>${esc((e.category || e.fi_types || '').replace(/_/g, ' '))}</td><td>${esc(e.amount_bucket || '')}</td></tr>`).join('') || '<tr><td colspan="3">No events yet.</td></tr>'}</tbody></table></section></div>`;
}
PAGES.find(p => p.id === 'privacy').after = () => {
  const g = $('#grantBtn'); if (g) g.onclick = async () => { try { await api('/consent/grant', { method: 'POST', body: {} }); toast('Consent given'); route(); } catch (e) { toast(e.message, true); } };
};


/* ---------- Know your money + inline term tooltips ---------- */
let GLOSS = null;
async function glossary() { if (!GLOSS) GLOSS = await api('/glossary'); return GLOSS; }
async function renderKnow() {
  const g = await glossary(), groups = [...new Set(g.map(t => t.group))];
  const open = decodeURIComponent(location.hash.split('?t=')[1] || '');
  return `<div class="card"><h2>Start here</h2><p class="sub">Money words sound scary, but each one is simple. Tap a word to open it. Each one shows what it means, an example in rupees, what it depends on, and how it changes.</p>
  <input class="input" id="gSearch" type="search" placeholder="Search a word, for example EMI" aria-label="Search terms" style="margin-top:12px"></div>
  ${groups.map(gr => `<section class="card gloss-group"><h2>${esc(gr)}</h2>${g.filter(t => t.group === gr).map(t =>
    `<details class="term" id="t-${esc(t.id)}" data-q="${esc((t.term + ' ' + t.simple).toLowerCase())}" ${t.id === open ? 'open' : ''}><summary>${esc(t.term)}</summary><p>${esc(t.simple)}</p>
    <dl><dt>Example</dt><dd>${esc(t.example)}</dd><dt>Depends on</dt><dd>${esc(t.depends)}</dd><dt>How it changes</dt><dd>${esc(t.changes)}</dd></dl></details>`).join('')}</section>`).join('')}`;
}
PAGES.find(p => p.id === 'know').after = v => { const o = v.querySelector('details[open]'); if (o) o.scrollIntoView({ block: 'center' }); };
const TERM_MAP = [[/\bregime\b/i, 'regime'], [/\badvance tax\b/i, 'advance_tax'], [/\bTDS\b/, 'tds'], [/\bEMI\b/, 'emi'], [/\bUPI\b/, 'upi'], [/\bELSS\b/, 'elss'],
  [/\bPPF\b/, 'ppf'], [/\bNPS\b/, 'nps'], [/\b80C\b/, '80C'], [/\b80D\b/, '80d'], [/\b87A\b/, '87A'], [/\bcess\b/i, 'cess'], [/\bslab\b/i, 'slab'],
  [/\btaxable income\b/i, 'taxable'], [/\bstandard deduction\b/i, 'standard_deduction'], [/\bsafety buffer\b/i, 'buffer'], [/\brunway\b/i, 'runway'],
  [/\btax drag\b/i, 'tax_drag'], [/\bdeductions?\b/i, 'deduction'], [/\bliquidity\b/i, 'liquidity'], [/\bconfidence\b/i, 'confidence'], [/\bSIP\b/, 'sip'], [/\bprecision\b/i, 'precision_recall']];
function linkTerms(root) {
  glossary().then(g => {
    const by = Object.fromEntries(g.map(t => [t.id, t])), seen = new Set(), nodes = [];
    const skip = new Set(['INPUT', 'TEXTAREA', 'BUTTON', 'A', 'SCRIPT', 'STYLE', 'SELECT', 'OPTION', 'H1', 'H2', 'TEXT', 'TITLE']);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) { const n = w.currentNode, p = n.parentElement; if (p && n.nodeValue.trim().length > 1 && !skip.has(p.tagName) && !p.closest('.gl,svg,summary,th')) nodes.push(n); }
    for (const n of nodes) {
      let node = n;
      for (const [rx, id] of TERM_MAP) {
        if (seen.has(id) || !by[id] || !node.parentNode) continue;
        const m = rx.exec(node.nodeValue); if (!m) continue;
        seen.add(id);
        const after = node.splitText(m.index), rest = after.splitText(m[0].length), sp = document.createElement('span');
        sp.className = 'gl'; sp.tabIndex = 0; sp.dataset.term = id; sp.title = by[id].term + ': ' + by[id].simple + ' (click to learn more)'; sp.textContent = m[0];
        after.replaceWith(sp); node = rest;
      }
    }
  }).catch(() => {});
}

/* ---------- global events ---------- */
document.addEventListener('click', async e => {
  const t = e.target.closest('[data-term],[data-tx],[data-close],[data-del],[data-act],[data-f],[data-revoke],[data-delinc],[data-fix],[data-delbill],[data-delrule],[data-retrain],[data-confirm],[data-more-close]'); if (!t) return;
  if (t.dataset.term) { location.hash = '#know?t=' + encodeURIComponent(t.dataset.term); return; }
  if (t.dataset.tx) return openDrawer(+t.dataset.tx);
  if (t.hasAttribute('data-close')) return closeDrawer();
  if (t.hasAttribute('data-more-close')) return closeMore();
  if (t.dataset.f) { txFilter = t.dataset.f; document.querySelectorAll('#txTabs .tab').forEach(b => b.setAttribute('aria-pressed', b === t)); return paintTx(); }
  if (t.dataset.act === 'demo') return loadDemo();
  if (t.dataset.act === 'add') return openAdd();
  try {
    if (t.dataset.confirm) { await api(`/transactions/${t.dataset.confirm}/confirm`, { method: 'POST' }); toast('Thanks. Marked as correct'); closeDrawer(); route(); }
    if (t.dataset.del) { await api(`/transactions/${t.dataset.del}`, { method: 'DELETE' }); closeDrawer(); toast('Transaction deleted'); route(); }
    if (t.dataset.fix) { const r = await api(`/transactions/${t.dataset.fix}/category`, { method: 'PATCH', body: { category: $('#fixCat').value, apply_to_similar: $('#fixSim').checked } });
      toast(r.updated_similar ? `Saved. ${r.updated_similar} similar message(s) updated too` : 'Category saved and remembered'); closeDrawer(); route(); }
    if (t.dataset.delbill) { await api(`/bills/${t.dataset.delbill}`, { method: 'DELETE' }); toast('Bill removed'); route(); }
    if (t.dataset.delrule) { await api(`/rules/${t.dataset.delrule}`, { method: 'DELETE' }); toast('Rule removed'); route(); }
    if (t.dataset.retrain) { const r = await api('/model/retrain', { method: 'POST' }); toast('Model refreshed: ' + (r.examples ?? r.n_examples ?? 'done') + ' examples'); route(); }
    if (t.dataset.revoke) { await api(`/consent/${t.dataset.revoke}/revoke`, { method: 'POST' }); toast('Consent withdrawn'); route(); }
    if (t.dataset.delinc) { await api(`/income/${t.dataset.delinc}`, { method: 'DELETE' }); toast('Month removed'); route(); }
  } catch (err) { toast(err.message, true); }
});
document.addEventListener('input', e => { if (e.target.id === 'gSearch') { const q = e.target.value.trim().toLowerCase(); document.querySelectorAll('details.term').forEach(d => { d.hidden = q && !d.dataset.q.includes(q); }); }
  if (e.target.id === 'txSearch') { txQuery = e.target.value; paintTx(); } });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (!$('#drawer').hidden) closeDrawer(); if (!$('#moreSheet').hidden) closeMore(); } });
$('#scrim').onclick = () => { closeDrawer(); closeMore(); };
$('#addBtn').onclick = openAdd;
$('#retryBtn').onclick = route;
$('#demoBtn').onclick = loadDemo;
$('#addDlg').addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.close(); });
async function loadDemo() {
  try {
    const has = (await api('/transactions?limit=1')).length;
    if (has && !confirm('This replaces your current transactions and income history with sample data. Continue?')) return;
    await api('/demo/load', { method: 'POST' }); toast('Demo data loaded'); route();
  } catch (e) { toast(e.message, true); }
}
window.addEventListener('hashchange', route);
/* boot (login, live updates, extra pages) is in account.js, loaded after this file */
