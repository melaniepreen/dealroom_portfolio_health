'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = value => value == null ? '—' : `${Math.round(value * 100)}%`;
const date = value => value ? new Intl.DateTimeFormat('en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(value)) : 'Unavailable';
let portfolio = [], alerts = [], descending = true, requestId = 0, horizon = 3, loadId = 0;
const dialog = $('detail');
const ring = score => `<div class="ring" style="--score:${score}"><svg viewBox="0 0 96 96" aria-hidden="true"><circle class="track" cx="48" cy="48" r="42"/><circle class="fill" cx="48" cy="48" r="42"/></svg><span class="ring-value">${pct(score)}<small>probability</small></span></div>`;
async function load() {
  const currentLoad = ++loadId;
  const selectedHorizon = horizon;
  $('error').hidden = true;
  document.querySelectorAll('[data-horizon]').forEach(button => button.disabled = true);
  try {
    const response = await fetch(`/portfolio?horizon=${selectedHorizon}`);
    if (!response.ok) throw new Error('Portfolio unavailable');
    const data = await response.json();
    if (currentLoad !== loadId) return;
    portfolio = data.companies;
    alerts = data.alerts;
    const scored = portfolio.filter(c => c.model_score != null).sort((a,b) => b.model_score-a.model_score || a.name.localeCompare(b.name));
    const high = scored.filter(c => c.model_score >= .7);
    $('signal-count').textContent = high.length;
    $('nav-count').textContent = high.length;
    $('company-count').textContent = portfolio.length;
    const latest = portfolio.map(c => c.as_of).filter(Boolean).sort().at(-1);
    $('data-date').textContent = latest ? `Model as of ${date(latest)}` : 'No model scores yet';
    $('data-source').textContent = portfolio.some(c => c.recorded_example) ? 'Recorded example data' : 'Live Dealroom records · Experimental model';
    $('signal-cards').classList.toggle('two-signals', high.length === 2);
    $('signal-cards').innerHTML = high.length ? high.slice(0,3).map((c,i) => `<a href="/?company=${encodeURIComponent(c.name)}" class="signal-card" data-company="${esc(c.name)}"><div class="card-top"><span class="signal-label">High signal</span><span class="card-rank">${i === 0 ? 'TOP SIGNAL' : 'ON THE RADAR'}</span></div><div class="card-main"><div><h3>${esc(c.name)}</h3><span class="industry">${esc(c.industry)}</span></div>${ring(c.model_score)}</div><div class="card-bottom"><span>Potential next raise <strong>· ${esc(c.next_stage || 'Unclassified')}</strong></span><span class="card-arrow" aria-hidden="true">↗</span></div></a>`).join('') : `<div class="loading">No company currently has a validated estimate above the 70% high-signal threshold over ${horizon} months. Missing scores mean there is not enough evidence to score the company.</div>`;
    const report = data.model?.metrics?.horizons?.[String(horizon)];
    if (report && !report.published && data.model?.metrics?.experimental) {
      $('signal-cards').innerHTML = '<div class="loading"><strong>Real data loaded. Scores awaiting validation.</strong><br>The model has been fitted to live Dealroom funding histories, but the independent evaluation sample has too few next-stage raises to support probabilities.</div>';
    }
    document.querySelector('.model-note').textContent = data.model?.metrics?.experimental ? `Experimental XGBoost · ${data.model.metrics.companies} real API companies · Funding history only. ${report?.reason || 'Validation pending'} High signal ≥ 70%.` : `High signal ≥ 70% · XGBoost estimate of reaching the next funding stage within ${horizon} months. Confirm timing with founders.`;
    $('signal-horizon').textContent = `XGBoost · Next ${horizon} months`;
    $('sort-label').textContent = `${horizon}-month signal`;
    $('outlook-period').textContent = horizon === 3 ? 'THE NEXT THREE MONTHS' : 'THE NEXT SIX MONTHS';
    document.querySelectorAll('[data-horizon]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.horizon) === horizon)));
    renderOutlook(data, latest, high);
    const selected = $('stage').value;
    $('stage').innerHTML = '<option value="">All stages</option>' + [...new Set(portfolio.map(c=>c.series).filter(Boolean))].map(stage=>`<option>${esc(stage)}</option>`).join('');
    $('stage').value = selected;
    renderRows();
    const name = new URLSearchParams(location.search).get('company');
    if (name) openDetail(name);
  } catch (error) {
    $('error').hidden = false;
    $('signal-cards').innerHTML = '';
    $('outlook-intro').textContent = 'Live portfolio unavailable. Retry to see an evidence-based outlook.';
    $('outlook-actions').innerHTML = '';
    $('data-date').textContent = 'Portfolio unavailable';
    $('showing').textContent = 'Unable to load companies';
    portfolio = [];
    renderRows();
  } finally {
    document.querySelectorAll('[data-horizon]').forEach(button => button.disabled = false);
  }
}
function renderRows() {
  const query = $('search').value.trim().toLowerCase();
  const stage = $('stage').value;
  const rows = portfolio.filter(c => `${c.name} ${c.industry}`.toLowerCase().includes(query) && (!stage || c.series === stage)).sort((a,b)=> {
    if (a.model_score == null) return b.model_score == null ? a.name.localeCompare(b.name) : 1;
    if (b.model_score == null) return -1;
    return (descending ? b.model_score-a.model_score : a.model_score-b.model_score) || a.name.localeCompare(b.name);
  });
  $('company-rows').innerHTML = rows.map(c => `<tr><td><div class="company-cell"><span class="company-icon" aria-hidden="true">${esc(c.name.charAt(0).toLowerCase())}</span><div><button class="company-name" data-company="${esc(c.name)}">${esc(c.name)}</button><span class="company-sector">${esc(c.industry)}</span></div></div></td><td><span class="stage-badge">${esc(c.series || 'Unknown')}</span></td><td class="last-round">${esc(c.last_venture_round || 'Unavailable')}</td><td><div class="score-cell"><span title="${esc(c.model_score == null ? (c.missing_features || []).join('; ') : 'Experimental calibrated estimate')}">${pct(c.model_score)}</span><span class="mini-track" aria-hidden="true"><i style="width:${c.model_score == null ? 0 : c.model_score*100}%"></i></span></div></td><td class="next-stage">${esc(c.next_stage || 'Unknown')}</td><td><button class="row-open" data-company="${esc(c.name)}" aria-label="View ${esc(c.name)}">↗</button></td></tr>`).join('');
  $('empty').hidden = !!rows.length;
  $('showing').textContent = `${rows.length} of ${portfolio.length} companies`;
  $('sort').setAttribute('aria-label', `Sort ${horizon}-month signal ${descending ? 'ascending' : 'descending'}`);
  $('sort').closest('th').setAttribute('aria-sort', descending ? 'descending' : 'ascending');
  $('sort-direction').textContent = descending ? '↓' : '↑';
}
async function openDetail(name) {
  const id = ++requestId;
  $('detail-content').innerHTML = `<h2 id="detail-title">${esc(name)}</h2><p class="detail-note" role="status">Loading company intelligence…</p>`;
  if (!dialog.open) dialog.showModal();
  history.replaceState(null,'',`/?company=${encodeURIComponent(name)}`);
  try {
    const response = await fetch(`/companies/${encodeURIComponent(name)}/brief`);
    if (!response.ok) throw new Error('Unavailable');
    const brief = await response.json();
    if(id !== requestId || !dialog.open) return;
    const c = portfolio.find(c => c.name === name);
    const s = brief.summary;
    const prediction = (brief.prediction?.horizons || []).find(p => p.months === horizon);
    const r = {next_stage: prediction?.next_stage || brief.readiness.next_stage, model_score: prediction?.model_score};
    const companyAlerts = alerts.filter(a=>a.company === name);
    $('detail-content').innerHTML = `<h2 id="detail-title">${esc(name)}</h2><p class="detail-subtitle">${esc(s.industry)} · ${esc(s.hq_country || 'Location unavailable')}</p><div class="detail-stats"><div><small>${horizon}-MONTH MODEL SIGNAL</small><strong>${pct(r.model_score)}</strong></div><div><small>CURRENT STAGE</small><strong>${esc(s.series || 'Unknown')}</strong></div><div><small>POTENTIAL NEXT STAGE</small><strong>${esc(r.next_stage || 'Unknown')}</strong></div></div><p class="detail-note">${esc(c?.model_version || 'Model version unavailable')} · As of ${date(c?.as_of)}. Experimental funding-history estimate; this does not confirm an active fundraise.</p><section class="detail-section"><h3>What needs your attention</h3>${companyAlerts.length ? companyAlerts.map(a=>`<div class="detail-alert"><strong>${esc(a.title)}</strong><p>${esc(a.summary)}</p><p>${esc(a.next_step)}</p></div>`).join('') : '<p class="detail-note">No additional alerts for this company.</p>'}</section><section class="detail-section"><h3>Funding history</h3>${brief.round_svg || '<p class="detail-note">No funding history available.</p>'}</section><section class="detail-section"><h3>Growth against peers</h3>${brief.graph_svg || '<p class="detail-note">Headcount data unavailable.</p>'}${brief.traffic_svg || '<p class="detail-note">Traffic data unavailable.</p>'}</section><details><summary>Model evidence & methodology</summary><p class="detail-note">XGBoost estimates whether the next standardised funding stage will be recorded in 3, 6 or 9 months. Feature gain describes the overall model fit, rather than a company-specific explanation.</p>${brief.horizon_svg || ''}<div class="table-scroll"><table class="feature-list"><thead><tr><th>Input</th><th>Stored value</th><th>Meaning</th></tr></thead><tbody>${brief.model_features.map(f=>`<tr><td>${esc(f.name)}</td><td>${esc(f.value ?? 'Missing')}</td><td>${esc(f.description)}</td></tr>`).join('')}</tbody></table></div><p class="detail-note">Missing inputs / score availability: ${esc((c?.missing_features || []).join(', ') || 'None recorded')}</p></details>`;
  } catch(error) {
    if(id === requestId) $('detail-content').innerHTML = `<h2 id="detail-title">${esc(name)}</h2><p>Company detail is unavailable. Please close this panel and try again.</p>`;
  }
}
document.addEventListener('click', e=> {
  const target = e.target.closest('[data-company]');
  if(target) {e.preventDefault();openDetail(target.dataset.company);}
});
$('close-detail').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{requestId++;history.replaceState(null,'','/');});
dialog.addEventListener('click', e=>{if(e.target === dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left || e.clientX>r.right || e.clientY<r.top || e.clientY>r.bottom)dialog.close();}});
$('search').addEventListener('input',renderRows);
$('stage').addEventListener('change',renderRows);
$('sort').addEventListener('click',()=>{descending=!descending;renderRows();});
$('retry').addEventListener('click',load);
load();

function renderOutlook(data, asOf, high) {
  let windowText = `${horizon} months from the model snapshot`;
  if (asOf) {
    const end = new Date(asOf);
    end.setUTCMonth(end.getUTCMonth() + horizon);
    windowText = `${date(asOf)} – ${date(end.toISOString())}`;
  }
  $('horizon-window').textContent = windowText;
  $('horizon-notes-title').textContent = horizon === 3 ? 'A three-month window' : 'A six-month window';
  $('demo-signal-label').textContent = `Illustrative ${horizon}-month high signal`;
  const report = data.model?.metrics?.horizons?.[String(horizon)];
  const published = report?.published === true;
  $('outlook-intro').textContent = published ? (high.length ? `${high.length} companies clear the ${horizon}-month high-signal threshold. Use the evidence below to prioritise founder conversations.` : `No company clears the ${horizon}-month high-signal threshold. Watch for commercial and funding milestones before changing priorities.`) : 'Focus on the next milestone, then the next round. Live probabilities are awaiting validation; these are diligence priorities, not model-backed fundraising recommendations.';
  const seeds = portfolio.filter(c => c.series === 'Seed').map(c => c.name);
  const missing = portfolio.filter(c => !c.last_venture_round).map(c => c.name);
  $('outlook-actions').innerHTML = `<article><span class="outlook-number">${horizon === 3 ? 'MONTH 1' : 'MONTHS 1–2'}</span><h3>Follow commercial progress</h3><p>${seeds.length ? esc(seeds.join(', ')) + ' are recorded at Seed. ' : ''}Look for paid customer conversion, retention and delivery against the milestones needed for a next-stage round.</p></article><article><span class="outlook-number">${horizon === 3 ? 'MONTH 2' : 'MONTHS 3–4'}</span><h3>Close the evidence gaps</h3><p>${missing.length ? esc(missing.join(' and ')) + ' have no recorded venture-round history in this import. ' : ''}Confirm financing dates, cash runway and the founders’ intended timetable directly.</p></article><article><span class="outlook-number">${horizon === 3 ? 'MONTH 3' : 'MONTHS 5–6'}</span><h3>Watch technical milestones</h3><p>For deep-tech opportunities, track independently verified performance, pilot-to-contract conversion and the capital required to reach the next engineering milestone.</p></article>`;
  $('horizon-caution').textContent = `Selected horizon: ${horizon} months (${windowText}). The outcome is a recorded transition to the next standardised stage. The backend fits 3-, 6- and 9-month models; all current live horizons remain experimental.`;
  $('validation-caution').textContent = published ? 'This experimental model passed its minimum validation checks. Its estimates still depend on the sample and reporting coverage.' : 'Live scores are withheld because the independent groups have too few next-stage outcomes. An unavailable score does not mean low fundraising potential.';
  const sets = report?.sets;
  $('validation-counts').textContent = sets ? `${horizon}-month model: ${sets.train.snapshots} training snapshots (${sets.train.positive} positive outcomes); ${sets.calibration.positive} positives in calibration and ${sets.test.positive} in testing. These are repeated snapshots, not distinct fundraising events.` : 'Validation sample counts are unavailable.';
}
$('show-demo').addEventListener('change', () => {
  $('demo-example').hidden = !$('show-demo').checked;
  document.querySelector('.demo-footnote').hidden = !$('show-demo').checked;
});
$('demo-detail').addEventListener('click', () => {
  requestId++;
  $('detail-content').innerHTML = `<span class="demo-badge">SYNTHETIC COMPANY · DEMO ONLY</span><h2 id="detail-title">Asterion Quantum</h2><p class="detail-subtitle">Deep technology · Quantum photonics</p><div class="detail-stats"><div><small>ILLUSTRATIVE SIGNAL</small><strong>84 / 100</strong></div><div><small>SCENARIO HORIZON</small><strong>${horizon} months</strong></div><div><small>POTENTIAL NEXT ROUND</small><strong>Series A</strong></div></div><p class="detail-note">The score is a preset demonstration value, not output from the live XGBoost model. All facts below are invented.</p><section class="detail-section"><h3>The hypothetical opportunity</h3><p>A Seed-stage photonics company raised £4m 18 months ago. It has two paid industrial pilots and is preparing an independently reviewed prototype benchmark.</p><h3>What would make a conversation timely?</h3><p>Signed annual contracts, reproducible technical performance, a costed manufacturing plan and a founder-confirmed Series A timetable within ${horizon} months.</p><h3>What could change the assessment?</h3><p>Pilot cancellations, failed benchmarks, low production yield, unverified runway or a capital requirement beyond the proposed round.</p><h3>What the live model can actually see</h3><p>Only dated funding-history features. The pilot, technical and runway evidence described here would require additional verified data and a separately validated model before it could influence a real score.</p></section>`;
  if (!dialog.open) dialog.showModal();
});

document.querySelectorAll('[data-horizon]').forEach(button => button.addEventListener('click', () => {
  const next = Number(button.dataset.horizon);
  if (next === horizon) return;
  horizon = next;
  if (dialog.open) dialog.close();
  load();
}));
