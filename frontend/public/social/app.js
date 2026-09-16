const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : 'https://clipvideo-production.up.railway.app';
const state = { accounts: [], clips: [], times: ['10:00', '15:00', '20:00'] };
const $ = (id) => document.getElementById(id);

function escapeHtml(value='') { return value.replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function isoForLocal(date, time) { return new Date(`${date}T${time}:00`).toISOString(); }
function captionFor(clip, index) { return $('caption').value.replaceAll('{clip_number}', String(clip.number ?? index + 1)).replaceAll('{total_clips}', String(state.clips.length)).replaceAll('{filename}', clip.filename || ''); }
function titleFor(clip, index) { return $('title').value.replaceAll('{clip_number}', String(clip.number ?? index + 1)).replaceAll('{total_clips}', String(state.clips.length)).replaceAll('{filename}', clip.filename || ''); }

function renderTimes() {
  $('times').innerHTML = state.times.map((time, i) => `<div class="time-row"><span>${i+1}</span><input type="time" value="${time}" data-time-index="${i}"><button class="icon" data-remove-time="${i}" ${state.times.length === 1 ? 'disabled' : ''}>×</button></div>`).join('');
  document.querySelectorAll('[data-time-index]').forEach(el => el.onchange = e => state.times[Number(e.target.dataset.timeIndex)] = e.target.value);
  document.querySelectorAll('[data-remove-time]').forEach(el => el.onclick = () => { state.times.splice(Number(el.dataset.removeTime), 1); renderTimes(); });
  renderPreview();
}

function renderAccounts() {
  const groups = ['instagram','facebook','threads','youtube','x'];
  $('providers').innerHTML = groups.map(provider => {
    const accounts = state.accounts.filter(a => a.provider === provider);
    const label = provider === 'x' ? 'X' : provider[0].toUpperCase()+provider.slice(1);
    const buttons = accounts.length ? accounts.map(a => `<label class="account"><input type="checkbox" value="${a.id}" data-account><span><b>${escapeHtml(a.display_name)}</b><small>${label}</small></span></label>`).join('') : `<button class="connect" data-connect="${provider === 'instagram' || provider === 'facebook' ? 'meta' : provider}">Connect ${label}</button>`;
    return `<article class="provider"><div class="provider-title"><span class="dot ${provider}"></span><h3>${label}</h3></div><div class="accounts">${buttons}</div></article>`;
  }).join('');
  document.querySelectorAll('[data-connect]').forEach(b => b.onclick = () => window.location.href = `${API}/api/v1/social/auth/${b.dataset.connect}/start`);
  document.querySelectorAll('[data-account]').forEach(b => b.onchange = renderPreview);
}

function renderClips() {
  $('clips').innerHTML = state.clips.length ? state.clips.map((c,i) => `<label class="clip"><input type="checkbox" checked data-clip-index="${i}"><span><b>#${c.number ?? i+1}</b> ${escapeHtml(c.filename || `Clip ${i+1}`)}</span><small>${Number(c.duration || 0).toFixed(1)}s</small></label>`).join('') : '<div class="empty">Load a completed job to see clips.</div>';
  document.querySelectorAll('[data-clip-index]').forEach(el => el.onchange = renderPreview);
  renderPreview();
}

function selectedClips() { return [...document.querySelectorAll('[data-clip-index]:checked')].map(el => state.clips[Number(el.dataset.clipIndex)]); }
function selectedAccounts() { return [...document.querySelectorAll('[data-account]:checked')].map(el => state.accounts.find(a => a.id === Number(el.value))).filter(Boolean); }

function renderPreview() {
  const clips = selectedClips(); const accounts = selectedAccounts(); const date = $('startDate').value;
  if (!clips.length || !accounts.length || !date || !state.times.length) { $('preview').innerHTML = '<div class="empty">Select clips, at least one connected account, a start date, and posting times.</div>'; return; }
  const rows = [];
  clips.slice(0, 12).forEach((clip, i) => {
    const slot = i % state.times.length; const day = Math.floor(i / state.times.length); const d = new Date(`${date}T00:00:00`); d.setDate(d.getDate()+day); const ds = d.toISOString().slice(0,10);
    rows.push(`<div class="preview-row"><b>${ds} · ${state.times[slot]}</b><span>Clip ${clip.number ?? i+1}</span><span>${accounts.map(a => escapeHtml(a.display_name)).join(', ')}</span></div>`);
  });
  $('preview').innerHTML = `<div class="preview-head">First ${Math.min(12, clips.length)} scheduled slots · ${clips.length * accounts.length} posts total</div>${rows.join('')}${clips.length>12?'<div class="more">…remaining slots generated automatically</div>':''}`;
}

async function loadProviders() {
  try { const r = await fetch(`${API}/api/v1/social/accounts`); const data = await r.json(); state.accounts = data.accounts || []; renderAccounts(); } catch { $('providers').innerHTML = '<div class="error">Social API is not reachable.</div>'; }
}

async function loadJob() {
  const id = $('jobId').value.trim(); if (!id) return;
  $('jobInfo').textContent = 'Loading job…';
  try {
    const r = await fetch(`${API}/api/v1/status/${encodeURIComponent(id)}`); const data = await r.json(); if (!r.ok) throw data;
    state.clips = data.clips || []; renderClips(); $('jobInfo').textContent = `${state.clips.length} clips loaded · status: ${data.status}`;
  } catch (e) { $('jobInfo').textContent = e.message || 'Could not load this job.'; }
}

async function refreshQueue() {
  try {
    const r = await fetch(`${API}/api/v1/social/posts?limit=500`); const data = await r.json();
    $('queue').innerHTML = (data.posts || []).map(p => `<div class="queue-row"><span class="badge ${p.status}">${p.status}</span><b>${escapeHtml(p.provider)}</b><span>${escapeHtml(p.display_name)}</span><time>${new Date(p.scheduled_at).toLocaleString()}</time><button class="cancel" data-cancel="${p.id}" ${p.status !== 'scheduled' ? 'disabled' : ''}>Cancel</button>${p.error ? `<small>${escapeHtml(p.error)}</small>`:''}</div>`).join('') || '<div class="empty">No scheduled posts yet.</div>';
    document.querySelectorAll('[data-cancel]').forEach(b => b.onclick = async () => { await fetch(`${API}/api/v1/social/posts/${b.dataset.cancel}`, {method:'DELETE'}); refreshQueue(); });
  } catch { $('queue').innerHTML = '<div class="error">Could not load queue.</div>'; }
}

async function schedule() {
  const clips = selectedClips(), accounts = selectedAccounts(), start = $('startDate').value;
  if (!clips.length || !accounts.length || !start || !state.times.length) { $('result').textContent = 'Complete the source and schedule settings first.'; return; }
  const posts = [];
  clips.forEach((clip, i) => {
    const slot = i % state.times.length; const day = Math.floor(i / state.times.length); const d = new Date(`${start}T00:00:00`); d.setDate(d.getDate()+day); const date = d.toISOString().slice(0,10); const scheduled_at = isoForLocal(date, state.times[slot]);
    accounts.forEach(account => posts.push({account_id: account.id, media_url: clip.download_url, caption: captionFor(clip,i), title: titleFor(clip,i), scheduled_at}));
  });
  $('schedule').disabled = true; $('result').textContent = `Creating ${posts.length} server-side jobs…`;
  try { const r = await fetch(`${API}/api/v1/social/posts/bulk`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({posts})}); const data = await r.json(); if(!r.ok) throw data; $('result').textContent = `✓ ${data.created} posts scheduled. You can close this website; the server queue will continue.`; refreshQueue(); } catch(e) { $('result').textContent = e.message || 'Scheduling failed.'; } finally { $('schedule').disabled = false; }
}

$('loadJob').onclick = loadJob;
$('refresh').onclick = refreshQueue;
$('schedule').onclick = schedule;
$('addTime').onclick = () => { state.times.push('12:00'); renderTimes(); };
$('autoTimes').onclick = () => { const n = Math.max(1, Math.min(24, Number($('perDay').value)||3)); state.times = Array.from({length:n},(_,i)=>{ const mins=Math.round((9*60+i*(12*60/Math.max(1,n-1)))); return `${String(Math.floor(mins/60)%24).padStart(2,'0')}:${String(mins%60).padStart(2,'0')}`; }); renderTimes(); };
$('perDay').onchange = () => { while(state.times.length < Number($('perDay').value)) state.times.push('12:00'); while(state.times.length > Number($('perDay').value)) state.times.pop(); renderTimes(); };
$('caption').oninput = renderPreview; $('title').oninput = renderPreview;

const today = new Date(); $('startDate').value = today.toISOString().slice(0,10);
const tz = Intl.DateTimeFormat().resolvedOptions().timeZone; $('timezone').innerHTML = [`<option>${tz}</option>`,`<option>UTC</option>`].join('');
renderTimes(); renderAccounts(); renderClips(); loadProviders(); refreshQueue();
