
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = value => value == null ? '—' : `${Math.round(value * 100)}%`;
const date = value => value ? new Intl.DateTimeFormat('en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(value)) : 'Unavailable';
let portfolio = [], alerts = [], demo = null, descending = true, requestId = 0, horizon = 3;
const dialog = $('detail');
const ring = score => `<div class="ring" style="--score:${score}"><svg viewBox="0 0 96 96" aria-hidden="true"><circle class="track" cx="48" cy="48" r="42"/><circle class="fill" cx="48" cy="48" r="42"/></svg><span class="ring-value">${pct(score)}<small>demo model</small></span></div>`;
async function load() {
  $('error').hidden = true;
  document.querySelectorAll('[data-horizon]').forEach(b => b.disabled = true);
  try {
    const responses = await Promise.all([fetch(`/portfolio?horizon=${horizon}`),fetch('/static/demo.json')]);
    if (responses.some(r => !r.ok)) throw new Error('Unavailable');
    const [data, example] = await Promise.all(responses.map(r => r.json()));
    demo = example;
    portfolio = [...data.companies, {...demo, model_score: demo.horizons[String(horizon)].score}];
    alerts = data.alerts;
    $('company-count').textContent = portfolio.length;
    $('nav-count').textContent = portfolio.filter(c => c.model_score >= .7).length;
    $('data-date').textContent = `As of ${date(demo.as_of)}`;
    $('data-source').textContent = 'Dealroom · XGBoost';
    $('sort-label').textContent = `${horizon}-month signal`;
    document.querySelectorAll('[data-horizon]').forEach(b => b.setAttribute('aria-pressed',String(Number(b.dataset.horizon)===horizon)));
    const selected = $('stage').value;
    $('stage').innerHTML = '<option value="">All stages</option>' + [...new Set(portfolio.map(c=>c.series).filter(Boolean))].map(s=>`<option>${esc(s)}</option>`).join('');
    $('stage').value = selected;
    renderSignal();
    renderRows();
    const name = new URLSearchParams(location.search).get('company');
    if (name) openDetail(name);
  } catch (error) {
    $('error').hidden = false;
    $('raise-content').textContent = 'Signal unavailable. Please retry.';
    portfolio = [];
    renderRows();
  } finally {
    document.querySelectorAll('[data-horizon]').forEach(b => b.disabled = false);
  }
}
function renderSignal() {
  const result=demo.horizons[String(horizon)];
  const reasons=result.evidence.filter(r=>r.contribution>0).slice(0,3);
  $('raise-content').innerHTML = `<div class="raise-main"><div><p class="raise-kicker">Seed → Series A <span class="demo-chip">Demo</span></p><button class="raise-company" data-company="${esc(demo.name)}">${esc(demo.name)} <span aria-hidden="true">↗</span></button><p class="raise-description">The synthetic-data XGBoost model estimates a next-stage raise likelihood of ${pct(result.score)} within ${horizon} months.</p></div>${ring(result.score)}</div><div class="raise-reasons">${reasons.map(r=>`<div><strong>${esc(r.value)}</strong><span>${esc(r.label)}</span></div>`).join('')}</div><div class="raise-bottom"><span>Top positive contributors to this company’s prediction</span><button class="model-link" data-company="${esc(demo.name)}">View model evidence ↗</button></div>`;
}
function demoModelCharts(result) {
  const horizons=Object.entries(demo.horizons);
  const predictionChart=`<svg viewBox="0 0 640 230" role="img" aria-label="Synthetic XGBoost next-raise predictions: ${horizons.map(([h,r])=>`${h} months ${pct(r.score)}`).join(', ')}"><title>Next-raise likelihood by prediction horizon</title>${[0,25,50,75,100].map(v=>`<line x1="76" y1="${180-v*1.4}" x2="605" y2="${180-v*1.4}" stroke="#e0e4dc"/><text x="60" y="${184-v*1.4}" text-anchor="end" fill="#747d75" font-size="12">${v}%</text>`).join('')}${horizons.map(([h,r],i)=>`<rect x="${165+i*250}" y="${180-r.score*140}" width="110" height="${r.score*140}" rx="6" fill="${Number(h)===horizon?'#426951':'#a6b89a'}"/><text x="${220+i*250}" y="${170-r.score*140}" text-anchor="middle" fill="#243c36" font-size="17">${pct(r.score)}</text><text x="${220+i*250}" y="207" text-anchor="middle" fill="#747d75" font-size="13">${h} months</text>`).join('')}</svg>`;
  const max=Math.max(...result.evidence.map(r=>Math.abs(r.contribution)),.001);
  const drivers=`<div class="driver-chart" role="img" aria-label="Company-specific model contributions in log-odds">${result.evidence.map(r=>`<div class="driver-row"><div class="driver-label"><span>${esc(r.label)}</span><strong>${r.contribution>=0?'+':''}${r.contribution.toFixed(3)}</strong></div><div class="driver-track"><span style="width:${Math.abs(r.contribution)/max*100}%;background:${r.contribution>=0?'#68835c':'#af8065'}"></span></div><small>${esc(r.value)}</small></div>`).join('')}</div>`;
  return `<section class="detail-section"><h3>Next-raise models</h3><p class="detail-note">Separate XGBoost models for each horizon · Seed → Series A</p>${predictionChart}<div class="demo-model-grid">${horizons.map(([h,r])=>`<div class="demo-model-card"><small>${h}-MONTH XGBOOST</small><strong>${pct(r.score)}</strong><span>Synthetic test Brier score ${r.brier_synthetic_test.toFixed(3)}</span></div>`).join('')}</div></section><section class="detail-section"><h3>What drives the ${horizon}-month signal</h3>${drivers}<p class="detail-note">TreeSHAP contributions in log-odds. Positive values push this company’s score up; they describe the model calculation, not causation.</p></section>`;
}
function openDemo() {
  requestId++;
  const result=demo.horizons[String(horizon)];
  history.replaceState(null,'',`/?company=${encodeURIComponent(demo.name)}`);
  $('detail-content').innerHTML=`<p class="raise-kicker">Deep technology · Quantum photonics <span class="demo-chip">Demo</span></p><h2 id="detail-title">${esc(demo.name)}</h2><div class="detail-stats"><div><small>NEXT ${horizon} MONTHS</small><strong>${pct(result.score)}</strong></div><div><small>CURRENT STAGE</small><strong>Seed</strong></div><div><small>NEXT STAGE</small><strong>Series A</strong></div></div>${demoModelCharts(result)}<section class="detail-section"><h3>Why the model flags this company</h3><p>The company’s synthetic profile includes 180% annual revenue growth, six paid pilots, a completed technical milestone, nine months of runway and 24 months since its last round.</p><div class="table-scroll"><table class="feature-list"><thead><tr><th>Model input</th><th>Company value</th><th>Contribution</th></tr></thead><tbody>${result.evidence.map(r=>`<tr><td>${esc(r.label)}</td><td>${esc(r.value)}</td><td>${r.contribution>0?'+':''}${r.contribution.toFixed(3)}</td></tr>`).join('')}</tbody></table></div><p class="detail-note">Company-specific TreeSHAP contributions are in log-odds: positive values push the prediction up. These describe this model’s calculation, not causation.</p></section><section class="detail-section"><h3>Training evidence</h3><p>XGBoost was fitted on ${demo.training_rows.toLocaleString()} synthetic company profiles and checked against ${demo.test_rows} separate synthetic profiles. The ${horizon}-month synthetic test Brier score is ${result.brier_synthetic_test.toFixed(3)} (lower is better).</p><p class="detail-note">${esc(demo.model_version)}. Training labels were simulated from funding cadence, revenue growth, pilots, technical milestones and runway. This fictional company and its computed score are isolated from the live Dealroom model; synthetic test results do not establish real-world accuracy.</p><h3>Investor follow-up</h3><p>Confirm pilot-to-contract conversion, benchmark reproducibility and the founders’ financing timetable before discussing the Series A.</p></section>`;
  if (!dialog.open) dialog.showModal();
}
function renderRows() {
  const query = $('search').value.trim().toLowerCase();
  const stage = $('stage').value;
  const rows = portfolio.filter(c => `${c.name} ${c.industry}`.toLowerCase().includes(query) && (!stage || c.series === stage)).sort((a,b)=> {
    if (a.model_score == null) return b.model_score == null ? a.name.localeCompare(b.name) : 1;
    if (b.model_score == null) return -1;
    return (descending ? b.model_score-a.model_score : a.model_score-b.model_score) || a.name.localeCompare(b.name);
  });
  $('company-rows').innerHTML = rows.map(c => `<tr><td><div class="company-cell"><span class="company-icon" aria-hidden="true">${esc(c.name.charAt(0).toLowerCase())}</span><div><button class="company-name" data-company="${esc(c.name)}">${esc(c.name)}${c.synthetic ? ' <span class="demo-chip">Demo</span>' : ''}</button><span class="company-sector">${esc(c.industry)}</span></div></div></td><td><span class="stage-badge">${esc(c.series || 'Unknown')}</span></td><td class="last-round">${esc(c.last_venture_round || 'Unavailable')}</td><td><div class="score-cell"><span title="${esc(c.model_score == null ? (c.missing_features || []).join('; ') : c.synthetic ? 'XGBoost score trained on synthetic data' : 'Experimental calibrated estimate')}">${pct(c.model_score)}</span><span class="mini-track" aria-hidden="true"><i style="width:${c.model_score == null ? 0 : c.model_score*100}%"></i></span></div></td><td class="next-stage">${esc(c.next_stage || 'Unknown')}</td><td><button class="row-open" data-company="${esc(c.name)}" aria-label="View ${esc(c.name)}">↗</button></td></tr>`).join('');
  $('empty').hidden = !!rows.length;
  $('showing').textContent = `${rows.length} of ${portfolio.length} companies · 1 demo`;
  $('sort').setAttribute('aria-label', `Sort ${horizon}-month signal ${descending ? 'ascending' : 'descending'}`);
  $('sort').closest('th').setAttribute('aria-sort', descending ? 'descending' : 'ascending');
  $('sort-direction').textContent = descending ? '↓' : '↑';
}
function peerCharts(report) {
  if (!report) return '<p class="detail-note">Peer benchmark import unavailable.</p>';
  const charts=Object.entries(report.series).map(([metric,points])=>{
    const valid=points.filter(p=>p.median!=null);
    const title=metric==='employees'?'Headcount · annual filings':'Website visits · monthly';
    if(!points.length) return `<h3>${title}</h3><p class="detail-note">Insufficient peer data: fewer than five observations per period.</p>`;
    const max=Math.max(1,...points.flatMap(p=>[p.median||0,p.company||0]));
    const x=i=>60+i*530/Math.max(1,points.length-1), y=v=>180-v/max*135;
    const marks=points.map((p,i)=>`${p.median==null?'':`<circle cx="${x(i)}" cy="${y(p.median)}" r="4" fill="#af8065"><title>${p.date}: peer median ${Math.round(p.median).toLocaleString()}, n=${p.count}</title></circle>`}${p.company==null?'':`<circle cx="${x(i)}" cy="${y(p.company)}" r="4" fill="#426951"><title>${p.date}: company ${Math.round(p.company).toLocaleString()}</title></circle>`}`).join('');
    const lines=['median','company'].map(key=>points.slice(1).map((p,i)=>p[key]!=null&&points[i][key]!=null?`<line x1="${x(i)}" y1="${y(points[i][key])}" x2="${x(i+1)}" y2="${y(p[key])}" stroke="${key==='median'?'#af8065':'#426951'}" stroke-width="2"/>`:'').join('')).join('');
    return `<h3>${title}</h3><svg viewBox="0 0 640 225" role="img" aria-label="${title}: company and global peer median"><text x="60" y="22" font-size="12" fill="#426951">Company</text><text x="170" y="22" font-size="12" fill="#af8065">Peer median</text>${[0,.5,1].map(v=>`<line x1="60" y1="${y(max*v)}" x2="590" y2="${y(max*v)}" stroke="#e0e4dc"/><text x="52" y="${y(max*v)+4}" text-anchor="end" font-size="10">${Math.round(max*v).toLocaleString()}</text>`).join('')}${lines}${marks}<text x="60" y="211" font-size="11">${points[0].date}</text><text x="590" y="211" text-anchor="end" font-size="11">${points[points.length-1].date}</text></svg><p class="detail-note">${valid.length ? `${Math.min(...valid.map(p=>p.count))}–${Math.max(...valid.map(p=>p.count))} reporting peers per plotted median.` : 'Peer median unavailable: fewer than five observations per period.'} Missing periods are not filled. Hover over a point for its count.</p>`;
  }).join('');
  return `<p class="detail-note">${esc(report.scope||'')} · ${esc(report.match||'')} · ${report.peers.length} candidates assessed. ${esc(report.status)}</p>${charts}<details><summary>Peer companies and coverage</summary><p class="detail-note">${report.peers.map(p=>`${esc(p.name)} (${esc(p.country||'country unavailable')})${p.error?' — history unavailable':''}`).join(' · ')}</p></details>`;
}
async function openDetail(name) {
  if (demo && name === demo.name) { openDemo(); return; }
  const id = ++requestId;
  $('detail-content').innerHTML = `<h2 id="detail-title">${esc(name)}</h2><p class="detail-note" role="status">Loading company intelligence…</p>`;
  if (!dialog.open) dialog.showModal();
  history.replaceState(null,'',`/?company=${encodeURIComponent(name)}`);
  try {
    const response = await fetch(`/companies/${encodeURIComponent(name)}/brief`);
    if (!response.ok) throw new Error('Unavailable');
    const brief = await response.json();
    const peerReport = await fetch("/static/peers.json").then(r=>r.ok?r.json():{}).then(data=>data[name]).catch(()=>null);
    if(id !== requestId || !dialog.open) return;
    const c = portfolio.find(c => c.name === name);
    const s = brief.summary;
    const prediction = (brief.prediction?.horizons || []).find(p => p.months === horizon);
    const r = {next_stage: prediction?.next_stage || brief.readiness.next_stage, model_score: prediction?.model_score};
    const companyAlerts = alerts.filter(a=>a.company === name);
    $('detail-content').innerHTML = `<h2 id="detail-title">${esc(name)}</h2><p class="detail-subtitle">${esc(s.industry)} · ${esc(s.hq_country || 'Location unavailable')}</p><div class="detail-stats"><div><small>${horizon}-MONTH MODEL SIGNAL</small><strong>${pct(r.model_score)}</strong></div><div><small>CURRENT STAGE</small><strong>${esc(s.series || 'Unknown')}</strong></div><div><small>POTENTIAL NEXT STAGE</small><strong>${esc(r.next_stage || 'Unknown')}</strong></div></div><p class="detail-note">${esc(c?.model_version || 'Model version unavailable')} · As of ${date(c?.as_of)}. Experimental funding-history estimate; this does not confirm an active fundraise.</p><section class="detail-section"><h3>What needs your attention</h3>${companyAlerts.length ? companyAlerts.map(a=>`<div class="detail-alert"><strong>${esc(a.title)}</strong><p>${esc(a.summary)}</p><p>${esc(a.next_step)}</p></div>`).join('') : '<p class="detail-note">No additional alerts for this company.</p>'}</section><section class="detail-section"><h3>Funding history</h3>${brief.round_svg || '<p class="detail-note">No funding history available.</p>'}</section><section class="detail-section"><h3>Growth against peers</h3>${peerCharts(peerReport)}</section><details><summary>Model evidence & methodology</summary><p class="detail-note">XGBoost estimates whether the next standardised funding stage will be recorded in 3, 6 or 9 months. Feature gain describes the overall model fit, rather than a company-specific explanation.</p>${brief.horizon_svg || ''}<div class="table-scroll"><table class="feature-list"><thead><tr><th>Input</th><th>Stored value</th><th>Meaning</th></tr></thead><tbody>${brief.model_features.map(f=>`<tr><td>${esc(f.name)}</td><td>${esc(f.value ?? 'Missing')}</td><td>${esc(f.description)}</td></tr>`).join('')}</tbody></table></div><p class="detail-note">Missing inputs / score availability: ${esc((c?.missing_features || []).join(', ') || 'None recorded')}</p></details>`;
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


document.querySelectorAll('[data-horizon]').forEach(button => button.addEventListener('click', () => {
  if (Number(button.dataset.horizon) === horizon) return;
  horizon = Number(button.dataset.horizon);
  if (dialog.open) dialog.close();
  load();
}));
