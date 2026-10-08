'use strict';
let state, csrf = '', configurationName = '', configurationDownload = '';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const endpoint = id => '/api/forwards/' + encodeURIComponent(id);
function notice(message='') { $('notice').textContent = message; }
async function request(path, method='GET', body) {
  const response = await fetch(path, {method, headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
async function attempt(fn) { try { notice(); await fn(); } catch(error) { notice(error.message); } }
function badge(enabled) { return '<span class="badge '+(enabled?'':'off')+'">'+(enabled?'Enabled':'Disabled')+'</span>'; }
function empty(message) { return '<div class="empty">'+message+'</div>'; }
async function refresh() {
  state = await request('/api/state'); csrf = state.csrf;
  $('login').hidden=true; $('dashboard').hidden=false; $('logout').hidden=false;
  $('mode').textContent=state.mode === 'preview' ? 'Preview · no network changes' : 'Live';
  $('subtitle').textContent='Tunnel network '+state.subnet+' · Managed public ports '+state.portMin+'–'+state.portMax;
  const open = new Set([...state.forwards.filter(f=>f.enabled).map(f=>f.publicPort), ...state.firewallRules.filter(r=>r.enabled).map(r=>r.port)]);
  $('stats').innerHTML = [[state.hosts.length,'WireGuard hosts'],[state.forwards.filter(f=>f.enabled).length,'Active forwards'],[open.size,'Allowed TCP ports']].map(([n,label])=>'<div class="stat"><b>'+n+'</b><span>'+label+'</span></div>').join('');
  $('forward-list').innerHTML=state.forwards.map(f=>{
    const button=(action,label)=>'<button data-action="'+action+'" data-id="'+esc(f.id)+'">'+label+'</button>';
    return '<article class="card"><div><h3>'+esc(f.id)+' '+badge(f.enabled)+'</h3><p>TCP · VPS :'+f.publicPort+' → '+esc(f.hostId)+' :'+f.targetPort+'</p>'+(f.hostname?'<p>'+esc(f.hostname)+' · DNS: '+esc(f.dnsStatus)+'</p>':'')+'</div><div class="actions">'+button('edit','Edit')+button('toggle',f.enabled?'Disable':'Enable')+(f.hostname?button('dns','Sync DNS'):'')+(f.dnsRecordId?button('undns','Remove DNS'):'')+button('delete','Delete')+'</div></article>';
  }).join('') || empty('Add a host, then create your first forwarding rule.');
  const wg=state.wireguard;
  $('wg-status').textContent=wg.available?wg.interface+' · VPS tunnel '+wg.serverAddress+' · Endpoint '+wg.endpoint:wg.message;
  $('windows-ready').textContent=wg.available?'Ready: UNM can configure a new peer on the VPS.':'Not ready to connect: '+wg.message+' Complete VPS setup and enable live mode before adding a new peer.';
  $('host-list').innerHTML=state.hosts.map(h=>{
    const peer=(wg.peers||[]).find(p=>p.publicKey===h.publicKey);
    const status=peer?.lastHandshake?'Last handshake '+new Date(peer.lastHandshake*1000).toLocaleString():(h.managed?'Waiting for first handshake':'Existing tunnel');
    return '<article class="card"><div><h3>'+esc(h.id)+' <span class="badge">'+(h.managed?'Managed peer':'Registered host')+'</span></h3><p>'+esc(h.address)+' · '+esc(status)+'</p></div><div class="actions">'+(h.managed?'<button data-host-action="configuration" data-id="'+esc(h.id)+'">Host setup</button>':'')+'<button data-host-action="delete" data-id="'+esc(h.id)+'">Remove</button></div></article>';
  }).join('') || empty('Register an existing host or create a new WireGuard peer.');
  $('firewall-list').innerHTML=[
    ...state.forwards.filter(f=>f.enabled).map(f=>'<article class="card"><div><h3>TCP '+f.publicPort+'</h3><p>Opened by forwarding rule '+esc(f.id)+'</p></div><span class="badge">Automatic</span></article>'),
    ...state.firewallRules.map(r=>'<article class="card"><div><h3>'+esc(r.id)+' '+badge(r.enabled)+'</h3><p>TCP '+r.port+'</p></div><div class="actions"><button data-firewall-action="toggle" data-id="'+esc(r.id)+'">'+(r.enabled?'Disable':'Enable')+'</button><button data-firewall-action="delete" data-id="'+esc(r.id)+'">Remove</button></div></article>')
  ].join('') || empty('No managed port allowances yet.');
  $('audit-list').innerHTML='<table><thead><tr><th>Time</th><th>Account</th><th>Change</th><th>Resource</th></tr></thead><tbody>'+state.audit.map(a=>'<tr><td>'+esc(new Date(a.at*1000).toLocaleString())+'</td><td>'+esc(a.actor)+'</td><td>'+esc(a.action)+'</td><td>'+esc(a.resource)+'</td></tr>').join('')+'</tbody></table>';
}
$('login-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{await request('/api/login','POST',Object.fromEntries(new FormData(e.target)));e.target.reset();await refresh();});};
$('logout').onclick=()=>attempt(async()=>{await request('/api/logout','POST',{});clearConfiguration();location.reload();});
$('refresh').onclick=()=>attempt(refresh);
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('.tab').forEach(tab=>tab.hidden=tab.id!==button.dataset.tab);document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));notice();});
function edit(rule) {
  const f=$('forward-form'); f.reset(); f.hidden=false;
  f.elements.hostId.innerHTML=state.hosts.map(h=>'<option value="'+esc(h.id)+'">'+esc(h.id)+' · '+esc(h.address)+'</option>').join('');
  f.elements.publicPort.min=state.portMin; f.elements.publicPort.max=state.portMax;
  f.elements.publicPort.value=state.portMin;
  f.elements.hostname.placeholder='media.'+state.dnsSuffix;
  f.elements.id.readOnly=Boolean(rule);
  if(rule) for(const [key,value] of Object.entries(rule)) if(f.elements[key]) {if(key==='enabled') f.elements[key].checked=value;else f.elements[key].value=value;}
  f.scrollIntoView({behavior:'smooth',block:'center'});
}
$('new-forward').onclick=()=>edit(); $('cancel-forward').onclick=()=>$('forward-form').hidden=true;
$('forward-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const b=Object.fromEntries(new FormData(f));b.targetPort=Number(b.targetPort);b.publicPort=Number(b.publicPort);b.enabled=f.elements.enabled.checked;await request(endpoint(b.id),'PUT',b);f.hidden=true;await refresh();});};
$('forward-list').onclick=e=>attempt(async()=>{
  const button=e.target.closest('[data-action]');if(!button)return;
  const f=state.forwards.find(f=>f.id===button.dataset.id);const action=button.dataset.action;
  if(action==='edit')return edit(f);
  if(['delete','undns'].includes(action)&&!confirm('Confirm '+(action==='delete'?'deleting the forwarding rule':'removing the DNS record')+' for '+f.id+'?'))return;
  if(action==='toggle')await request(endpoint(f.id),'PUT',{...f,enabled:!f.enabled});
  if(action==='delete')await request(endpoint(f.id),'DELETE');
  if(action==='dns')await request(endpoint(f.id)+'/dns','POST',{});
  if(action==='undns')await request(endpoint(f.id)+'/dns','DELETE');
  await refresh();
});
function setupMethod() {
  const enroll=$('host-setup').value==='new';
  $('peer-options').hidden=!enroll;$('host-address').required=!enroll;$('host-address').placeholder=enroll?'Automatic if left blank':'10.8.0.2';
}
$('host-setup').onchange=setupMethod;
$('new-host').onclick=()=>{const f=$('host-form');f.reset();f.hidden=false;setupMethod();f.scrollIntoView({behavior:'smooth',block:'center'});};
$('cancel-host').onclick=()=>$('host-form').hidden=true;
function showConfiguration(id, result) {
  configurationName=id; configurationDownload=result.configuration; $('host-config').hidden=false;
  $('config-text').value=result.privateKeyIncluded?result.configuration:result.configuration.replace(/^\[Interface\]\r?\nPrivateKey = <HOST_PRIVATE_KEY>\r?\n/, '');
  $('config-note').textContent=result.privateKeyIncluded?'Save this file now. Its private key is shown once and is not stored by UNM. Keep the file private.':'Keep the [Interface] and PrivateKey lines already in your Windows empty tunnel. Paste the settings below after that private-key line. Your private key stays on your PC.';
  $('copy-config').textContent=result.privateKeyIncluded?'Copy complete configuration':'Copy settings for empty tunnel';
  $('download-config').textContent=result.privateKeyIncluded?'Download .conf':'Download template .conf';
  $('config-windows-steps').textContent=result.privateKeyIncluded?'Windows: import the downloaded file using Add Tunnel → Import tunnel(s) from file. Or paste the complete configuration into an empty tunnel, replacing all its existing text. Save and activate.':'Windows: name the tunnel, paste these settings below the existing PrivateKey line, then Save → Activate. The downloadable template still needs your private key inserted locally before it can be imported.';
  $('host-config').scrollIntoView({behavior:'smooth',block:'center'});
}
function clearConfiguration() { $('config-text').value='';$('host-config').hidden=true;configurationName='';configurationDownload=''; }
$('close-config').onclick=clearConfiguration;
$('copy-config').onclick=async()=>{try{await navigator.clipboard.writeText($('config-text').value);notice('Copied. Paste into WireGuard on your Windows PC.');}catch(error){$('config-text').focus();$('config-text').select();notice('The settings are selected. Press Ctrl+C to copy, then paste into WireGuard.');}};
$('download-config').onclick=()=>{const blob=new Blob([configurationDownload],{type:'text/plain'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=configurationName+'.conf';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('host-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{
  const f=e.target;const b=Object.fromEntries(new FormData(f));b.enroll=b.setup==='new';delete b.setup;
  const submit=f.querySelector('button');submit.disabled=true;
  try{const result=await request('/api/hosts','POST',b);f.hidden=true;if(result.configuration)showConfiguration(b.id,result);await refresh();}
  finally{submit.disabled=false;}
});};
$('host-list').onclick=e=>attempt(async()=>{
  const button=e.target.closest('[data-host-action]');if(!button)return;const id=button.dataset.id;
  if(button.dataset.hostAction==='configuration'){showConfiguration(id,await request('/api/hosts/'+encodeURIComponent(id)+'/configuration'));return;}
  const host=state.hosts.find(h=>h.id===id);
  if(confirm(host.managed?'Remove '+id+' and its WireGuard peer from the VPS?':'Remove '+id+' from UNM? Its existing WireGuard peer stays in place.')){
    await request('/api/hosts/'+encodeURIComponent(id),'DELETE');clearConfiguration();await refresh();
  }
});
$('new-firewall').onclick=()=>{const f=$('firewall-form');f.reset();f.hidden=false;f.elements.port.min=state.portMin;f.elements.port.max=state.portMax;f.elements.port.value=state.portMin;};
$('cancel-firewall').onclick=()=>$('firewall-form').hidden=true;
$('firewall-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const b=Object.fromEntries(new FormData(f));b.port=Number(b.port);b.enabled=f.elements.enabled.checked;await request('/api/firewall','POST',b);f.hidden=true;await refresh();});};
$('firewall-list').onclick=e=>attempt(async()=>{const button=e.target.closest('[data-firewall-action]');if(!button)return;const r=state.firewallRules.find(r=>r.id===button.dataset.id);if(button.dataset.firewallAction==='toggle')await request('/api/firewall','POST',{...r,enabled:!r.enabled});else if(confirm('Remove this port allowance?'))await request('/api/firewall/'+encodeURIComponent(r.id),'DELETE');else return;await refresh();});
refresh().catch(()=>{});
