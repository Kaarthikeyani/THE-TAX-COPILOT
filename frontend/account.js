/* Account layer: phone + code sign-in, live updates, Connect phone, Ask. Loaded after app.js. */

/* ---------- sign in ---------- */
let loginPhone = '', resendTimer = null, DEMO = false;
async function showLogin(msg) {
  authed = false; stopLive();
  document.querySelector('.app').hidden = true; $('#login').hidden = false;
  document.body.classList.add('is-login');
  try { DEMO = !!(await api('/auth/mode')).demo; } catch (_) {}
  paintLogin(DEMO ? 'demo' : 'phone', msg);
}

/* ---------- demo sign-in: fake phone + code, then a short profile for new numbers (nothing real is checked or stored) ---------- */
const DEMO_LOGO = `<div class="login-logo"><svg viewBox="0 0 32 32" width="42" height="42" aria-hidden="true"><rect width="32" height="32" rx="9" fill="#0b7a75"/><path d="M9 21l5-6 4 4 5-8" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
let demoPhone = '';
function paintDemo(step, msg, info) {
  const el = $('#loginCard'), num = (id) => +($('#' + id).value || 0);
  const note = `<div class="callout gold" style="margin-bottom:14px">${ICON.info}<span><b>Demo with fake data.</b> No real phone number, code or bank access. Please do not type real personal details.</span></div>`;
  if (step === 'demo') {
    el.innerHTML = `${DEMO_LOGO}<div><b>Tax &amp; Cash Co-Pilot</b><span>Sign in to the live demo</span></div></div>
      ${msg ? `<div class="callout gold" style="margin-bottom:14px">${ICON.info}<span>${esc(msg)}</span></div>` : ''}${note}
      <form id="dPhone" novalidate><div class="field"><label for="d_phone">Mobile number</label>
        <input class="input" id="d_phone" type="tel" inputmode="numeric" maxlength="14" placeholder="Any 3 to 12 digits, e.g. 123" required autofocus>
        <small>Use a new number to create a new person. Use the same number later to come back to them.</small></div>
        <div id="lg_err" class="form-err" role="alert"></div><button class="btn primary wide" id="d_go" type="submit">Send code</button></form>
      <div class="login-links" style="margin-top:12px"><span class="sub">Quick start:</span>
        <button type="button" class="linkish" data-quick="111">Priya, salaried (111)</button><button type="button" class="linkish" data-quick="222">Arjun, freelancer (222)</button></div>`;
    const go = async n => { $('#lg_err').textContent = ''; const b = $('#d_go'); b.disabled = true; b.textContent = 'Sending…';
      try { const r = await api('/auth/demo/request', { method: 'POST', body: { phone: n } }); demoPhone = r.phone; paintLogin('democode', null, r); }
      catch (err) { $('#lg_err').textContent = err.message; b.disabled = false; b.textContent = 'Send code'; } };
    $('#dPhone').onsubmit = e => { e.preventDefault(); go($('#d_phone').value.trim()); };
    document.querySelectorAll('[data-quick]').forEach(b => b.onclick = () => go(b.dataset.quick));
    return;
  }
  if (step === 'democode') {
    el.innerHTML = `${DEMO_LOGO}<div><b>Enter your code</b><span>Sent to ${esc(info.phone)}</span></div></div>
      <div class="callout gold" style="margin-bottom:14px">${ICON.info}<span><b>Demo code:</b> <button type="button" class="linkish" id="d_fill">${esc(info.demo_code)}</button> (tap to fill). In the real app this arrives by SMS.</span></div>
      <form id="dCode" novalidate><div class="field"><label for="d_code">6-digit code</label>
        <input class="input code" id="d_code" inputmode="numeric" maxlength="6" placeholder="••••••" required autofocus></div>
        <div id="lg_err" class="form-err" role="alert"></div><button class="btn primary wide" id="d_ver" type="submit">Verify and continue</button></form>
      <div class="login-links"><button type="button" class="linkish" id="d_back">Change number</button></div>`;
    $('#d_fill').onclick = () => { $('#d_code').value = info.demo_code; $('#d_code').focus(); };
    $('#d_back').onclick = () => paintLogin('demo');
    $('#dCode').onsubmit = async e => { e.preventDefault(); const b = $('#d_ver'); b.disabled = true; b.textContent = 'Checking…'; $('#lg_err').textContent = '';
      try { const r = await api('/auth/demo/start', { method: 'POST', body: { phone: demoPhone, code: $('#d_code').value } });
        if (r.needs_profile) return paintLogin('onboard', null, { code: $('#d_code').value });
        TK.set(r.token); await startApp(); toast('Welcome back'); }
      catch (err) { $('#lg_err').textContent = err.message; b.disabled = false; b.textContent = 'Verify and continue'; } };
    return;
  }
  const code = info.code;
  const f = (id, label, ph, extra = '', cls = 'field') => `<div class="${cls}"><label for="${id}">${label}</label><input class="input" id="${id}" ${extra} placeholder="${ph}"></div>`;
  const money = (id, label, ph) => f(id, label, ph, 'type="number" inputmode="numeric" min="0"');
  el.innerHTML = `${DEMO_LOGO}<div><b>Create your profile</b><span>New number ${esc(demoPhone)} · takes a minute</span></div></div>${note}
    <form id="dOnb" class="form-grid" novalidate>
      <div class="field full"><label for="o_name">Your name</label><input class="input" id="o_name" placeholder="e.g. Ravi Kumar" required autofocus></div>
      <div class="field full"><label>How do you earn?</label><div class="seg" id="o_type"><button type="button" data-v="salaried" aria-pressed="true">Salaried</button><button type="button" data-v="freelancer" aria-pressed="false">Freelancer / self-employed</button></div></div>
      ${f('o_job', 'Work / role', 'e.g. Software engineer')}${f('o_emp', 'Employer or business', 'e.g. TCS')}
      ${money('o_sal', 'Monthly salary or income (₹)', '80000')}${f('o_age', 'Age', '30', 'type="number" min="18" max="100" value="30"')}
      ${money('o_exp', 'Monthly spending (₹)', 'Leave blank to estimate')}${money('o_bal', 'Savings in bank (₹)', '150000')}
      ${money('o_fd', 'Other savings: FD, RD, cash (₹)', '0')}${money('o_inv', 'Investments, current value (₹)', 'Mutual funds, stocks, PPF')}
      ${f('o_invn', 'What are you invested in?', 'e.g. Index fund SIP, PPF', '', 'field full')}
      <div class="field"><label for="o_lt">Existing loan</label><select class="input" id="o_lt"><option value="">None</option><option value="home">Home</option><option value="car">Car</option><option value="personal">Personal</option><option value="education">Education</option></select></div>
      ${money('o_emi', 'Loan EMI per month (₹)', '0')}${money('o_out', 'Loan still owed (₹)', '0')}${money('o_int', 'Home loan interest per year (₹)', '0')}
      <div id="lg_err" class="form-err full" role="alert"></div>
      <div class="full"><button class="btn primary wide" id="o_go" type="submit">Create my demo account</button><p class="fine">We will fill your account with fake bank messages that match these answers.</p></div></form>`;
  document.querySelectorAll('#o_type button').forEach(b => b.onclick = () => document.querySelectorAll('#o_type button').forEach(x => x.setAttribute('aria-pressed', x === b)));
  $('#dOnb').onsubmit = async e => { e.preventDefault(); $('#lg_err').textContent = '';
    if (!$('#o_name').value.trim()) { $('#lg_err').textContent = 'Please enter your name.'; return; }
    const b = $('#o_go'); b.disabled = true; b.textContent = 'Building your sandbox…';
    const profile = { name: $('#o_name').value.trim(), income_type: $('#o_type [aria-pressed="true"]').dataset.v, occupation: $('#o_job').value.trim(), employer: $('#o_emp').value.trim(),
      monthly_salary: num('o_sal'), age: num('o_age') || 30, monthly_expenses: num('o_exp'), current_balance: num('o_bal'), savings_other: num('o_fd'),
      investments_value: num('o_inv'), investments_note: $('#o_invn').value.trim(), loan_type: $('#o_lt').value, loan_emi: num('o_emi'), loan_outstanding: num('o_out'), home_loan_interest: num('o_int') };
    try { const r = await api('/auth/demo/start', { method: 'POST', body: { phone: demoPhone, code, profile } }); TK.set(r.token); await startApp(); toast(`Welcome, ${profile.name.split(' ')[0]}! Ask the co-pilot anything`); }
    catch (err) { $('#lg_err').textContent = err.message; b.disabled = false; b.textContent = 'Create my demo account'; } };
}
function paintLogin(step, msg) {
  const el = $('#loginCard');
  if (step === 'demo' || step === 'democode' || step === 'onboard') return paintDemo(step, msg, arguments[2]);
  if (step === 'phone') {
    el.innerHTML = `<div class="login-logo"><svg viewBox="0 0 32 32" width="42" height="42" aria-hidden="true"><rect width="32" height="32" rx="9" fill="#0b7a75"/><path d="M9 21l5-6 4 4 5-8" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <div><b>Tax &amp; Cash Co-Pilot</b><span>Sign in with your phone number</span></div></div>
      ${msg ? `<div class="callout gold" style="margin-bottom:14px">${ICON.info}<span>${esc(msg)}</span></div>` : ''}
      <form id="phoneForm" novalidate><div class="field"><label for="lg_phone">Mobile number</label>
        <div class="phone-in"><span>+91</span><input class="input" id="lg_phone" type="tel" inputmode="tel" autocomplete="tel-national" placeholder="98765 43210" required autofocus></div>
        <small>We text you a 6-digit code. No password to remember. Other country? Type the number starting with +.</small></div>
        <div id="lg_err" class="form-err" role="alert"></div>
        <button class="btn primary wide" id="lg_send" type="submit">Send code</button></form>
      <p class="fine">By continuing you agree this is decision support, not tax or investment advice. Your messages stay encrypted and tied to your account only.</p>`;
    $('#phoneForm').onsubmit = async e => {
      e.preventDefault(); const raw = $('#lg_phone').value.trim(), btn = $('#lg_send'); $('#lg_err').textContent = '';
      if (!raw) { $('#lg_err').textContent = 'Enter your mobile number.'; return; }
      btn.disabled = true; btn.textContent = 'Sending…';
      try { const r = await api('/auth/otp/request', { method: 'POST', body: { phone: raw.startsWith('+') || raw.startsWith('00') ? raw : '+91' + raw.replace(/^0+/, '').replace(/^91(?=\d{10}$)/, '') } });
        loginPhone = raw.startsWith('+') || raw.startsWith('00') ? raw : '+91' + raw.replace(/^0+/, '').replace(/^91(?=\d{10}$)/, ''); paintLogin('code', null, r); }
      catch (err) { $('#lg_err').textContent = err.message; btn.disabled = false; btn.textContent = 'Send code'; }
    };
  } else {
    const r = arguments[2] || {};
    el.innerHTML = `<div class="login-logo"><svg viewBox="0 0 32 32" width="42" height="42" aria-hidden="true"><rect width="32" height="32" rx="9" fill="#0b7a75"/><path d="M9 21l5-6 4 4 5-8" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <div><b>Enter your code</b><span>Sent to ${esc(r.phone || loginPhone)}</span></div></div>
      ${r.dev_code ? `<div class="callout gold" style="margin-bottom:14px">${ICON.info}<span><b>Local test mode.</b> Your code is <button type="button" class="linkish" id="lg_fill">${esc(r.dev_code)}</button> (tap to fill). Real texting is off; see the README to turn it on.</span></div>`
        : r.provider === 'console' ? `<div class="callout gold" style="margin-bottom:14px">${ICON.info}<span>Texting is not set up on this server, so the code was printed in the server window (where you ran <code>python run.py</code>).</span></div>` : ''}
      <form id="codeForm" novalidate><div class="field"><label for="lg_code">6-digit code</label>
        <input class="input code" id="lg_code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••" required autofocus></div>
        <div id="lg_err" class="form-err" role="alert"></div>
        <button class="btn primary wide" id="lg_go" type="submit">Verify and continue</button></form>
      <div class="login-links"><button type="button" class="linkish" id="lg_back">Change number</button><button type="button" class="linkish" id="lg_resend" disabled>Resend code</button></div>`;
    const fill = $('#lg_fill'); if (fill) fill.onclick = () => { $('#lg_code').value = r.dev_code; $('#lg_code').focus(); };
    let left = r.resend_after || 30; const rb = $('#lg_resend');
    clearInterval(resendTimer);
    const tick = () => { if (!rb.isConnected) return clearInterval(resendTimer); rb.disabled = left > 0; rb.textContent = left > 0 ? `Resend in ${left}s` : 'Resend code'; left--; };
    tick(); resendTimer = setInterval(tick, 1000);
    rb.onclick = async () => { rb.disabled = true; try { const n = await api('/auth/otp/request', { method: 'POST', body: { phone: loginPhone } }); toast('New code sent'); paintLogin('code', null, n); } catch (err) { $('#lg_err').textContent = err.message; left = 30; } };
    $('#lg_back').onclick = () => paintLogin('phone');
    $('#lg_code').addEventListener('input', e => { e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6); if (e.target.value.length === 6) $('#codeForm').requestSubmit(); });
    $('#codeForm').onsubmit = async e => {
      e.preventDefault(); const btn = $('#lg_go'); $('#lg_err').textContent = '';
      btn.disabled = true; btn.textContent = 'Checking…';
      try { const v = await api('/auth/otp/verify', { method: 'POST', body: { phone: loginPhone, code: $('#lg_code').value, device: navigator.userAgent.slice(0, 60) } });
        TK.set(v.token); clearInterval(resendTimer);
        await startApp(); toast(v.adopted_existing_rows ? 'Welcome back. Your earlier data is now in your account' : v.is_new ? 'Welcome! Start by adding your income in Profile' : 'Signed in'); }
      catch (err) { $('#lg_err').textContent = err.message; btn.disabled = false; btn.textContent = 'Verify and continue'; $('#lg_code').select(); }
    };
  }
}
async function signOut() { try { await api('/auth/logout', { method: 'POST' }); } catch (_) {} TK.clear(); showLogin(); }

/* ---------- live updates (Server-Sent Events over fetch, so the token stays in a header) ---------- */
let liveAbort = null, liveRetry = 0, liveTimer = null;
function setLive(state) {
  const p = $('#livePill'); if (!p) return;
  p.dataset.state = state; p.querySelector('span').textContent = state === 'on' ? 'Live' : state === 'wait' ? 'Reconnecting' : 'Offline';
  p.title = state === 'on' ? 'New bank messages appear here as they arrive' : 'Trying to reconnect…';
}
function stopLive() { if (liveAbort) liveAbort.abort(); liveAbort = null; clearTimeout(liveTimer); setLive('off'); }
async function startLive() {
  stopLive(); const ac = new AbortController(); liveAbort = ac; setLive('wait');
  try {
    const res = await fetch(API + '/stream', { headers: { Authorization: 'Bearer ' + TK.get() }, signal: ac.signal });
    if (res.status === 401) return showLogin('Please sign in again.');
    if (!res.ok || !res.body) throw new Error('stream');
    liveRetry = 0; setLive('on');
    const rd = res.body.getReader(), dec = new TextDecoder(); let buf = '';
    for (;;) {
      const { value, done } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf('\n\n')) >= 0) { const block = buf.slice(0, i); buf = buf.slice(i + 2); handleLive(block); }
    }
  } catch (e) { if (ac.signal.aborted) return; }
  if (ac.signal.aborted || !authed) return;
  setLive('wait'); liveRetry = Math.min(liveRetry + 1, 6);
  liveTimer = setTimeout(startLive, Math.min(1000 * 2 ** liveRetry, 20000));
}
const LIVE_PAGES = new Set(['overview', 'transactions', 'tax', 'monthly', 'plan', 'accuracy']);  // not Connect: it would wipe the test result
const liveRefresh = debounce(() => {
  const id = (location.hash || '#overview').slice(1).split('?')[0];
  const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (LIVE_PAGES.has(id) && !typing && $('#drawer').hidden && !$('#addDlg').open) route();
}, 600);
function handleLive(block) {
  const ev = (/^event: (.+)$/m.exec(block) || [])[1], data = (/^data: (.+)$/m.exec(block) || [])[1];
  if (!data || ev === 'hello') return;
  let d; try { d = JSON.parse(data); } catch (_) { return; }
  if (ev === 'txn') { const t = d.txn; toast(`${t.type === 'credit' ? '+' : '-'}${inr(t.amount)} ${t.type === 'credit' ? 'from' : 'to'} ${t.merchant || 'unknown'} · ${t.label}`); }
  liveRefresh();
}

/* ---------- Connect phone ---------- */
async function renderConnect() {
  const [me, c] = await Promise.all([api('/me'), api('/me/connect')]);
  const setup = 'TCP1:' + btoa(c.url + '\n' + c.key);
  const bodyTpl = JSON.stringify({ messages: [{ text: '%body%', sender: '%from%', received_at: '%timestamp%' }] });
  const cp = (v, what) => `<button class="btn small" data-copy="${esc(v)}" data-what="${what}">Copy</button>`;
  const row = (k, v, what, mono = true) => `<div class="crow"><span>${k}</span><code class="${mono ? 'mono' : ''}">${esc(v)}</code>${cp(v, what)}</div>`;
  return `<div class="callout ${me.phone_connected ? 'good' : 'gold'}" style="margin-bottom:18px">${me.phone_connected ? ICON.check : ICON.info}
      <span>${me.phone_connected ? `<b>Your phone is connected.</b> Last message arrived ${esc(ago(me.last_sms_at))}.` : '<b>Your phone is not connected yet.</b> Until it is, you can paste messages by hand with Add transaction.'}</span></div>
    ${c.local_only ? `<div class="callout bad" style="margin-bottom:18px">${ICON.info}<span><b>Your phone cannot reach this address.</b> <code>${esc(c.url)}</code> only works on this computer. To let a phone on the same Wi-Fi in, stop the server and start it again with your computer's address, for example:
      <pre class="plain" style="margin-top:8px">$env:COPILOT_HOST="0.0.0.0"; $env:COPILOT_ALLOWED_HOSTS="192.168.1.20"; $env:COPILOT_PUBLIC_URL="http://192.168.1.20:8811"; python run.py</pre>
      Replace 192.168.1.20 with your computer's address (<code>ipconfig</code>). This is plain HTTP, so use it only on a network you trust, or put HTTPS in front.</span></div>` : ''}
    <div class="grid g2"><section class="card"><h2>1. Install the phone app (Android)</h2>
      <p class="sub">A web page cannot read your phone's inbox, so a small app on the phone sends each <b>bank</b> message here. It filters on the phone: personal chats and OTP codes never leave it.</p>
      <div class="row-actions" style="margin:12px 0"><a class="btn primary" href="/android/tax-copilot-sms.apk" download>Download phone app (APK)</a><button class="btn" data-copy="${esc(setup)}" data-what="setup code">Copy setup code</button></div>
      <p class="sub" style="font-size:12.5px">Open the downloaded file on your phone (allow "install unknown apps" for your browser when asked), open <b>Tax Co-Pilot SMS</b>, paste the setup code, allow SMS access, then press Send a test message. Prefer another app (Tasker, MacroDroid, an SMS forwarder)? Use the values below.</p>
      <div class="creds">${row('Address (POST)', c.url, 'address')}${row('Header name', c.header, 'header name')}${row('Header value (your private key)', c.key, 'key')}${row('Body (JSON)', bodyTpl, 'body')}</div>
      <p class="sub" style="font-size:12.5px;margin-top:10px">Replace <code>%body%</code>, <code>%from%</code> and <code>%timestamp%</code> with whatever your forwarder app calls the message text, sender and time. Only bank senders such as <code>AX-HDFCBK</code> are saved; texts from people are ignored.</p>
      <div class="row-actions" style="margin-top:14px"><button class="btn" id="rotateKey">Make a new key</button></div></section>
    <section class="card"><h2>2. Check that it works</h2>
      <p class="sub">This sends a sample bank message the same way your phone will. It should appear in Activity within a second, with a "Live" notice.</p>
      <button class="btn primary" id="testHook" style="margin-top:12px">Send a test message</button><div id="testOut" style="margin-top:12px"></div>
      <h2 style="margin-top:26px">Good to know</h2><ul class="limits"><li>Messages are saved only to <b>your</b> account. Another person using this app has their own key and cannot see yours.</li>
      <li>Sending the same message twice does not create a second entry.</li><li>If your phone is off or offline, most forwarder apps retry later. Nothing is lost.</li>
      <li>iPhone does not allow any app to read SMS, so on iPhone use Add transaction.</li></ul></section></div>
    <section class="card" style="margin-top:18px"><h2>Your account</h2><p class="sub">Signed in as ${esc(me.phone)} since ${fmtDate(me.member_since.slice(0, 10))}.</p>
      <div class="row-actions" style="margin-top:12px"><button class="btn" id="signOut">Sign out</button><button class="btn danger" id="delAcct">Delete my account and data</button></div></section>`;
}
async function connectAfter() {
  document.querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => { try { await navigator.clipboard.writeText(b.dataset.copy); toast('Copied ' + b.dataset.what); } catch (_) { toast('Select the text and copy it by hand', true); } });
  const t = $('#testHook'); if (t) t.onclick = async () => {
    t.disabled = true; const key = (await api('/me/connect')).key; const d = new Date(), ds = `${String(d.getDate()).padStart(2, '0')}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getFullYear()).slice(2)}`;
    try { const res = await fetch(API + '/sms/webhook', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        body: JSON.stringify({ messages: [{ text: `Rs.${(100 + Math.floor(Math.random() * 400)).toFixed(2)} debited from A/c XX0000 on ${ds} to VPA test-cafe@ybl (UPI Ref ${Date.now() % 1e6}). Bal Rs 50,000.00`, sender: 'AX-TESTBK', id: 'test-' + Date.now() }] }) });
      const j = await res.json(); const r = (j.results || [])[0] || {};
      $('#testOut').innerHTML = res.ok && r.status === 'saved' ? `<div class="callout good">${ICON.check}<span>Delivered and filed as <b>${esc(r.category.replace(/_/g, ' '))}</b>. You can delete it from Activity.</span></div>`
        : `<div class="callout bad">${ICON.info}<span>${esc(r.detail || (j.detail && j.detail.detail) || 'Failed')}</span></div>`;
    } catch (e) { $('#testOut').innerHTML = `<div class="callout bad">${ICON.info}<span>${esc(e.message)}</span></div>`; }
    t.disabled = false;
  };
  const rk = $('#rotateKey'); if (rk) rk.onclick = async () => { if (!confirm('Your phone stops working until you paste the new key into the forwarder app. Continue?')) return; await api('/me/connect/rotate', { method: 'POST' }); toast('New key created'); route(); };
  const so = $('#signOut'); if (so) so.onclick = signOut;
  const da = $('#delAcct'); if (da) da.onclick = async () => {
    if (prompt('This permanently erases your account, messages, rules and plans. Type DELETE to confirm.') !== 'DELETE') return;
    try { await api('/me', { method: 'DELETE' }); TK.clear(); toast('Account deleted'); showLogin(); } catch (e) { toast(e.message, true); } };
}

/* ---------- Ask ---------- */
const chat = [];
async function renderAsk() {
  const sys = await api('/system');
  const sug = ['Which tax regime is better for me?', 'Can I afford to prepay my loan, or should I invest?', 'Am I saving enough? What is my emergency fund status?', 'How can I save more tax this year?'];
  const l = sys.llm || {};
  return `<div class="callout ${l.available ? 'brand' : 'gold'}" style="margin-bottom:16px">${ICON.info}<span>${l.available
      ? (l.provider === 'claude' || l.provider === 'gemini' ? `Your co-pilot is an AI (<b>${l.provider === 'claude' ? 'Claude' : 'Gemini'}</b>) that <b>reasons</b> over your own numbers. Tax and plan figures come from the app's engines; the AI explains and advises, and flags any figure it worked out itself.`
        : `Answers are written by <b>${esc(l.model)}</b>, running on this computer. Figures come from the app's engines.`)
      : 'The AI model is not connected on this server, so answers use fixed rules.'}</span></div>
    <section class="card chatbox"><div id="chatLog" class="chatlog" aria-live="polite">${chat.length ? chat.map(chatBubble).join('') : '<p class="sub">Ask about your tax, loans, savings or investments. It remembers the conversation, so you can follow up.</p>'}</div>
      <div class="chips-row">${sug.map(q => `<button type="button" class="sample" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div>
      <form id="askForm" class="askform"><input class="input" id="askQ" maxlength="400" placeholder="Ask a question about your money…" aria-label="Your question" autocomplete="off" required>
        <button class="btn" id="micBtn" type="button" aria-label="Speak your question" title="Speak your question" hidden>🎤</button><button class="btn primary" id="askGo" type="submit">Ask</button></form>
      <p class="sub" style="font-size:12.5px;margin-top:10px">Decision support, not licensed tax or investment advice. For big decisions, check with a chartered accountant.</p></section>`;
}
function chatBubble(m) {
  if (m.role === 'user') return `<div class="bub me">${esc(m.text)}</div>`;
  const g = m.grounding || {};
  const src = m.source === 'llm' ? `<span class="chip brand">AI · ${esc(m.model)}</span>` : '<span class="chip gold">Rules-based answer</span>';
  const ground = g.ok ? `<span class="chip good">${g.figures_checked ? `${g.figures_checked} figure${g.figures_checked > 1 ? 's' : ''} match your data` : 'No money figures to check'}</span>`
    : `<span class="chip gold" title="The AI calculated these itself from your numbers. Check the working.">AI-calculated: ${g.unmatched.map(v => inr(v)).join(', ')}</span>`;
  return `<div class="bub bot"><p>${esc(m.text).replace(/\n/g, '<br>')}</p><div class="meta">${src}${ground}<span class="chip">${(m.latency_ms / 1000).toFixed(1)}s</span></div>
    ${m.note ? `<p class="sub" style="font-size:12.5px;margin-top:6px">${esc(m.note)}</p>` : ''}
    ${m.reasoning ? `<details class="why"><summary>How I worked this out</summary><p class="sub" style="white-space:pre-wrap">${esc(m.reasoning)}</p></details>` : ''}
    <details class="why"><summary>Facts used</summary><pre class="plain">${esc(JSON.stringify(m.facts, null, 1))}</pre></details></div>`;
}
function askAfter() {
  const log = $('#chatLog'); if (!log) return; log.scrollTop = log.scrollHeight;
  const send = async q => {
    const history = chat.slice(-8).map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', text: m.text }));
    chat.push({ role: 'user', text: q }); log.insertAdjacentHTML('beforeend', chatBubble(chat.at(-1)) + '<div class="bub bot typing" id="typing"><i></i><i></i><i></i></div>'); log.scrollTop = log.scrollHeight;
    $('#askGo').disabled = true;
    try { const r = await api('/ask', { method: 'POST', body: { question: q, history } });
      chat.push({ role: 'bot', text: r.answer, source: r.source, model: r.model, latency_ms: r.latency_ms, grounding: r.grounding, note: r.note, facts: r.facts_used, reasoning: r.reasoning });
      $('#typing')?.remove(); log.insertAdjacentHTML('beforeend', chatBubble(chat.at(-1)));
    } catch (e) { $('#typing')?.remove(); toast(e.message, true); }
    $('#askGo').disabled = false; log.scrollTop = log.scrollHeight;
  };
  $('#askForm').onsubmit = e => { e.preventDefault(); const q = $('#askQ').value.trim(); if (q.length < 3) return; $('#askQ').value = ''; send(q); };
  document.querySelectorAll('[data-q]').forEach(b => b.onclick = () => send(b.dataset.q));
  if (window.pendingAsk) { const q = window.pendingAsk; window.pendingAsk = null; send(q); }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition, mic = $('#micBtn');  // voice input: the browser's own speech-to-text, nothing is uploaded by us
  if (SR && mic) { mic.hidden = false; mic.onclick = () => { const r = new SR(); r.lang = 'en-IN'; r.interimResults = false; mic.disabled = true; mic.textContent = '…';
    r.onresult = ev => { $('#askQ').value = ev.results[0][0].transcript; $('#askQ').focus(); }; r.onend = r.onerror = () => { mic.disabled = false; mic.textContent = '🎤'; }; try { r.start(); } catch (_) { mic.disabled = false; mic.textContent = '🎤'; } }; }
}

/* ---------- boot ---------- */
PAGES.splice(3, 0, { id: 'ask', primary: true, label: 'Ask', icon: 'chat', title: 'Ask your co-pilot', sub: 'Plain answers about your tax and your money, based on your own numbers.', render: renderAsk, after: askAfter });
PAGES.splice(PAGES.findIndex(p => p.id === 'profile') + 1, 0, { id: 'connect', label: 'Connect phone', icon: 'phone', title: 'Connect your phone', sub: 'Send bank messages here automatically, as they arrive.', render: renderConnect, after: connectAfter });

/* Section order, most important first. Bottom bar on phones shows the five marked primary. */
const ORDER = ['overview', 'ask', 'know', 'transactions', 'monthly', 'tax', 'plan', 'profile', 'privacy', 'accuracy', 'connect'], PRIMARY = ['overview', 'ask', 'know', 'transactions', 'monthly'];
PAGES.sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
PAGES.forEach(p => { p.primary = PRIMARY.includes(p.id); });

async function startApp() {
  document.body.classList.remove('is-login'); $('#login').hidden = true; document.querySelector('.app').hidden = false;
  authed = true;
  if (DEMO && !document.getElementById('demoBanner')) {
    const b = document.createElement('div'); b.id = 'demoBanner';
    b.style.cssText = 'background:#fff4d6;color:#5c4400;text-align:center;font-size:13px;padding:6px 12px';
    b.textContent = 'Demo with fake data. Nothing here is real or connected to a bank. Sandboxes are cleared after a day.';
    document.body.prepend(b);
  }
  buildNav(); refreshWho(); startLive(); route();
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && authed && !liveAbort) startLive(); });
$('#signOutBtn').onclick = signOut;
$('#retryBtn').onclick = () => location.reload();
(async function boot() {
  try { DEMO = !!(await api('/auth/mode')).demo; } catch (_) {}
  if (DEMO) { const i = PAGES.findIndex(p => p.id === 'connect'); if (i >= 0) PAGES.splice(i, 1); }
  buildNav();
  if (!TK.get()) return showLogin();
  try { await api('/me'); await startApp(); } catch (e) { if (TK.get()) { $('#offline').hidden = false; document.querySelector('.app').hidden = false; $('#login').hidden = true; } }
})();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
