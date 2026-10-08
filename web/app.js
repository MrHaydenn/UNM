'use strict';
let state, csrf = '';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const endpoint = id => '/api/v1/minecraft/servers/' + encodeURIComponent(id);
function notice(message='') { $('notice').textContent = message; }
async function api(path, method='GET', body) {
  const response = await fetch(path, {method, headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
async function attempt(fn) { try { notice(); await fn(); } catch(error) { notice(error.message); } }
async function refresh() {
  state = await api('/api/state'); csrf = state.csrf;
  $('login').hidden=true; $('dashboard').hidden=false; $('logout').hidden=false;
  $('mode').textContent=state.mode === 'preview' ? 'Preview · no network changes' : 'Live';
  $('subtitle').textContent=`Reserved public ports ${state.portMin}–${state.portMax} · DNS under ${state.dnsSuffix}`;
  $('stats').innerHTML = [[state.hosts.length,'Registered PCs'],[state.servers.filter(s=>s.enabled).length,'Enabled routes'],[state.tokens.length,'API tokens']].map(([n,label])=>`<div class="stat"><b>${n}</b><span>${label}</span></div>`).join('');
  $('server-list').innerHTML=state.servers.map(s=>`<article class="card"><div><h3>${esc(s.id)} <span class="badge ${s.enabled?'':'off'}">${s.enabled?'Enabled':'Disabled'}</span></h3><p>VPS :${s.publicPort} → ${esc(s.hostId)} :${s.targetPort}</p><p>${esc(s.hostname || 'No hostname')} · DNS: ${esc(s.dnsStatus)}</p></div><div class="actions"><button data-action="edit" data-id="${esc(s.id)}">Edit</button><button data-action="toggle" data-id="${esc(s.id)}">${s.enabled?'Disable':'Enable'}</button><button data-action="dns" data-id="${esc(s.id)}">Sync DNS</button>${s.dnsRecordId?`<button data-action="undns" data-id="${esc(s.id)}">Remove DNS</button>`:''}<button data-action="delete" data-id="${esc(s.id)}">Delete</button></div></article>`).join('') || '<div class="empty">No server routes yet. Register a PC, then add your first server.</div>';
  $('host-list').innerHTML=state.hosts.map(h=>`<article class="card"><div><h3>${esc(h.id)}</h3><p>${esc(h.address)}</p></div><span class="badge">Registered</span></article>`).join('') || '<div class="empty">Add a PC using its existing WireGuard address.</div>';
  $('token-list').innerHTML=state.tokens.map(t=>`<article class="card"><div><h3>${esc(t.id)}</h3><p>Servers: ${esc(t.servers.join(', '))} · Ports: ${t.portMin}–${t.portMax}</p><p>Expires ${esc(new Date(t.expires*1000).toLocaleString())}</p></div><button data-revoke="${esc(t.id)}">Revoke</button></article>`).join('') || '<div class="empty">No launcher tokens yet.</div>';
  $('audit-list').innerHTML='<table><thead><tr><th>Time</th><th>Account</th><th>Change</th><th>Resource</th></tr></thead><tbody>'+state.audit.map(a=>`<tr><td>${esc(new Date(a.at*1000).toLocaleString())}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td>${esc(a.resource)}</td></tr>`).join('')+'</tbody></table>';
  const f=$('token-form'); for(const name of ['portMin','portMax']) if(!f.elements[name].value) f.elements[name].value=state[name];
}
$('login-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{await api('/api/login','POST',Object.fromEntries(new FormData(e.target)));e.target.reset();await refresh();});};
$('logout').onclick=()=>attempt(async()=>{await api('/api/logout','POST',{});location.reload();});
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('.tab').forEach(tab=>tab.hidden=tab.id!==button.dataset.tab);document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));notice();});
function edit(server) {
  const f=$('server-form'); f.reset(); f.hidden=false;
  f.elements.hostId.innerHTML=state.hosts.map(h=>`<option value="${esc(h.id)}">${esc(h.id)} · ${esc(h.address)}</option>`).join('');
  f.elements.publicPort.min=state.portMin; f.elements.publicPort.max=state.portMax;
  f.elements.publicPort.value=state.portMin;
  f.elements.hostname.placeholder='survival.'+state.dnsSuffix;
  f.elements.id.readOnly=Boolean(server);
  if(server) for(const [key,value] of Object.entries(server)) if(f.elements[key]) {if(key==='enabled') f.elements[key].checked=value;else f.elements[key].value=value;}
  f.scrollIntoView({behavior:'smooth',block:'center'});
}
$('new-server').onclick=()=>edit(); $('cancel-server').onclick=()=>$('server-form').hidden=true;
$('server-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const b=Object.fromEntries(new FormData(f));b.targetPort=Number(b.targetPort);b.publicPort=Number(b.publicPort);b.enabled=f.elements.enabled.checked;await api(endpoint(b.id),'PUT',b);f.hidden=true;await refresh();});};
$('server-list').onclick=e=>attempt(async()=>{const button=e.target.closest('[data-action]');if(!button)return;const s=state.servers.find(s=>s.id===button.dataset.id);const action=button.dataset.action;if(action==='edit')return edit(s);if(['delete','undns'].includes(action)&&!confirm(`Confirm ${action==='delete'?'deleting the route':'removing the DNS record'} for ${s.id}?`))return;if(action==='toggle')await api(endpoint(s.id),'PUT',{...s,enabled:!s.enabled});if(action==='delete')await api(endpoint(s.id),'DELETE');if(action==='dns')await api(endpoint(s.id)+'/dns','POST',{});if(action==='undns')await api(endpoint(s.id)+'/dns','DELETE');await refresh();});
$('host-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{await api('/api/hosts','POST',Object.fromEntries(new FormData(e.target)));e.target.reset();await refresh();});};
$('token-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const b=Object.fromEntries(new FormData(e.target));for(const key of ['hosts','servers'])b[key]=b[key].split(',').map(s=>s.trim()).filter(Boolean);for(const key of ['portMin','portMax','days'])b[key]=Number(b[key]);const result=await api('/api/tokens','POST',b);$('token-secret').value=result.token;$('token-reveal').hidden=false;await refresh();});};
$('dismiss-token').onclick=()=>{$('token-secret').value='';$('token-reveal').hidden=true;};
$('token-list').onclick=e=>attempt(async()=>{const b=e.target.closest('[data-revoke]');if(b&&confirm('Revoke this token immediately?')){await api('/api/tokens/'+encodeURIComponent(b.dataset.revoke),'DELETE');await refresh();}});
refresh().catch(()=>{});
