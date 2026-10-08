'use strict';
let state, csrf = '', configurationName = '', configurationDownload = '';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const endpoint = id => '/api/forwards/' + encodeURIComponent(id);
function notice(message='') {
  $('notice').textContent = message;
  const hostForm=$('host-form');
  let inline=$('host-error');
  if(!inline){inline=document.createElement('p');inline.id='host-error';inline.setAttribute('role','alert');hostForm.appendChild(inline);}
  inline.textContent=hostForm.hidden?'':message;
  if(message && hostForm.hidden) $('notice').scrollIntoView({behavior:'smooth',block:'center'});
}
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
  $('stats').innerHTML = [[state.hosts.length,'WireGuard hosts'],[state.forwards.filter(f=>f.enabled).length,'Active forwards'],[open.size,'Managed port entries']].map(([n,label])=>'<div class="stat"><b>'+n+'</b><span>'+label+'</span></div>').join('');
  $('forward-list').innerHTML=state.forwards.map(f=>{
    const button=(action,label)=>'<button data-action="'+action+'" data-id="'+esc(f.id)+'">'+label+'</button>';
    return '<article class="card"><div><h3>'+esc(f.name||f.id)+' '+badge(f.enabled)+'</h3><p>' +esc((f.protocol||'tcp').toUpperCase())+' · VPS :'+f.publicPort+' → '+esc(f.hostId)+' :'+f.targetPort+'</p>'+'</div><div class="actions">'+button('edit','Edit')+'<button role="switch" aria-checked="'+f.enabled+'" data-action="toggle" data-id="'+esc(f.id)+'">'+(f.enabled?'On':'Off')+'</button>'+button('delete','Delete')+'</div></article>';
  }).join('') || empty('Add a host, then create your first forwarding rule.');
  const wg=state.wireguard;
  $('wg-status').textContent=wg.available?wg.interface+' · VPS tunnel '+wg.serverAddress+' · Endpoint '+wg.endpoint:wg.message;
  $('windows-ready').textContent=wg.available && wg.provisioningEnabled && state.mode==='live'?'Ready: UNM can configure a new peer on the VPS.':'Not ready to connect: '+(wg.message||'Peer provisioning is disabled.')+' Complete VPS setup and enable live mode before adding a new peer.';
  $('host-list').innerHTML=state.hosts.map(h=>{
    const peer=peerForHost(h); const connected=peer?.lastHandshake && Date.now()/1000-peer.lastHandshake<180; const dot='<span class="status-dot '+(!wg.available?'unknown':connected?'connected':'disconnected')+'" title="'+(!wg.available?'Unknown':connected?'Recent handshake':'No recent handshake')+'"></span>';
    const status=peer?.lastHandshake?'Last handshake '+new Date(peer.lastHandshake*1000).toLocaleString():(h.managed?'Waiting for first handshake':'Existing tunnel');
    return '<article class="card"><div><h3>'+dot+esc(h.id)+' <span class="badge">'+(h.managed?'Managed peer':'Registered host')+'</span></h3><p>'+esc(h.address)+' · '+esc(status)+'</p></div><div class="actions">'+(h.managed?'<button data-host-action="configuration" data-id="'+esc(h.id)+'">Host setup</button>':'')+'<button data-host-action="delete" data-id="'+esc(h.id)+'">Remove</button></div></article>';
  }).join('') || empty('Register an existing host or create a new WireGuard peer.');
  $('firewall-list').innerHTML=[
    ...state.forwards.filter(f=>f.enabled).map(f=>'<article class="card"><div><h3>'+esc((f.protocol||'tcp').toUpperCase())+' '+f.publicPort+'</h3><p>Opened by forwarding rule '+esc(f.name||f.id)+'</p></div><span class="badge">Automatic</span></article>'),
    ...state.firewallRules.map(r=>'<article class="card"><div><h3>'+esc(r.name||r.id)+' '+badge(r.enabled)+'</h3><p>'+esc((r.protocol||'tcp').toUpperCase())+' '+r.port+'</p></div><div class="actions"><button role="switch" aria-checked="'+r.enabled+'" data-firewall-action="toggle" data-id="'+esc(r.id)+'">'+(r.enabled?'On':'Off')+'</button><button data-firewall-action="edit" data-id="'+esc(r.id)+'">Edit</button><button data-firewall-action="delete" data-id="'+esc(r.id)+'">Remove</button></div></article>')
  ].join('') || empty('No managed port allowances yet.');
  const fw=state.firewall; const active=fw.running??fw.enabled; $('firewall-master').setAttribute('aria-checked',String(active)); $('firewall-master').textContent=active?'On':'Off'; $('firewall-master').disabled=state.mode==='live'&&!fw.controllable; $('firewall-status').textContent=fw.preview?'Preview · saved setting '+(fw.enabled?'on':'off'):fw.running===null?'Service status unavailable':(fw.running?'Running':'Stopped')+(fw.controllable?'':' · service control disabled in VPS settings');
  renderServices();
  renderIntegrationKeys();
  await renderTraffic();
  $('audit-list').innerHTML='<table><thead><tr><th>Time</th><th>Account</th><th>Change</th><th>Resource</th></tr></thead><tbody>'+state.audit.map(a=>'<tr><td>'+esc(new Date(a.at*1000).toLocaleString())+'</td><td>'+esc(a.actor)+'</td><td>'+esc(a.action)+'</td><td>'+esc(a.resource)+'</td></tr>').join('')+'</tbody></table>';
}
$('login-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{await request('/api/login','POST',Object.fromEntries(new FormData(e.target)));e.target.reset();await refresh();});};
$('logout').onclick=()=>attempt(async()=>{await request('/api/logout','POST',{});clearConfiguration();clearKey();location.reload();});
$('refresh').onclick=()=>attempt(refresh);
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('.tab').forEach(tab=>tab.hidden=tab.id!==button.dataset.tab);document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));notice();});
function edit(rule) {
  const f=$('forward-form'); f.reset(); f.hidden=false;
  f.elements.hostId.innerHTML=state.hosts.map(h=>'<option value="'+esc(h.id)+'">'+esc(h.id)+' · '+esc(h.address)+'</option>').join('');
  f.elements.publicPort.min=state.portMin; f.elements.publicPort.max=state.portMax;
  f.elements.publicPort.value=state.portMin;
  f.elements.id.value='';
  f.elements.id.readOnly=Boolean(rule);
  if(rule) f.elements.name.value=rule.name||rule.id;
  if(rule) for(const [key,value] of Object.entries(rule)) if(f.elements[key]) {if(key==='enabled') f.elements[key].checked=value;else f.elements[key].value=value;}
  f.scrollIntoView({behavior:'smooth',block:'center'});
}
$('new-forward').onclick=()=>edit(); $('cancel-forward').onclick=()=>$('forward-form').hidden=true;
$('forward-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const b=Object.fromEntries(new FormData(f));b.enabled=f.elements.enabled.checked;await request(b.id?endpoint(b.id):'/api/forwards',b.id?'PUT':'POST',b);f.hidden=true;await refresh();});};
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
$('new-firewall').onclick=()=>{const f=$('firewall-form');f.reset();f.elements.id.value='';f.elements.id.readOnly=false;f.hidden=false;f.elements.port.min=state.portMin;f.elements.port.max=state.portMax;f.elements.port.value=state.portMin;};
$('cancel-firewall').onclick=()=>$('firewall-form').hidden=true;
$('firewall-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const b=Object.fromEntries(new FormData(f));b.enabled=f.elements.enabled.checked;await request('/api/firewall','POST',b);f.hidden=true;await refresh();});};
$('firewall-list').onclick=e=>attempt(async()=>{const button=e.target.closest('[data-firewall-action]');if(!button)return;const r=state.firewallRules.find(r=>r.id===button.dataset.id);if(button.dataset.firewallAction==='edit'){const f=$('firewall-form');f.reset();f.hidden=false;for(const [k,v] of Object.entries(r))if(f.elements[k]){if(k==='enabled')f.elements[k].checked=v;else f.elements[k].value=v;}f.elements.id.readOnly=true;return;}if(button.dataset.firewallAction==='toggle')await request('/api/firewall','POST',{...r,enabled:!r.enabled});else if(confirm('Remove this port allowance?'))await request('/api/firewall/'+encodeURIComponent(r.id),'DELETE');else return;await refresh();});
refresh().catch(()=>{});

function peerForHost(h){return (state.wireguard.peers||[]).find(p=>(h.publicKey&&p.publicKey===h.publicKey)||(p.allowedIPs||[]).includes(h.address+'/32'));}
function bytes(n){if(n<1024)return n+' B';const i=Math.min(4,Math.floor(Math.log(n)/Math.log(1024)));return (n/1024**i).toFixed(2)+' '+['B','KiB','MiB','GiB','TiB'][i];}
function rate(n){return (n*8/1000000).toFixed(3)+' Mbit/s';}
async function renderTraffic(){const t=await request('/api/traffic?days='+$('traffic-period').value);$('traffic-note').textContent=t.message;$('traffic-stats').innerHTML=[['Received',bytes(t.rx)],['Sent',bytes(t.tx)],['Receive rate',rate(t.rxRate)],['Send rate',rate(t.txRate)]].map(([label,value])=>'<div class="stat"><b>'+value+'</b><span>'+label+'</span></div>').join('');$('traffic-peers').innerHTML=t.peers.map(p=>{const host=state.hosts.find(h=>peerForHost(h)?.publicKey===p.peer);return '<article class="card"><div><h3>'+esc(host?.id||'Unregistered peer '+p.peer.slice(0,8))+'</h3><p>Received '+bytes(p.rx)+' · Sent '+bytes(p.tx)+'</p><p>'+rate(p.rxRate)+' in · '+rate(p.txRate)+' out</p></div></article>';}).join('')||empty('Waiting for the first successful traffic sample.');$('traffic-daily').innerHTML='<table><thead><tr><th>Day</th><th>Received</th><th>Sent</th></tr></thead><tbody>'+t.daily.map(d=>'<tr><td>'+esc(d.day)+'</td><td>'+bytes(d.rx)+'</td><td>'+bytes(d.tx)+'</td></tr>').join('')+'</tbody></table>';}
$('traffic-period').onchange=()=>attempt(renderTraffic);
$('firewall-master').onclick=()=>attempt(async()=>{const enabled=!((state.firewall.running??state.firewall.enabled));if(!enabled&&state.mode==='live'&&!confirm('Stop all of firewalld? This removes firewall protection for every service on the VPS.'))return;await request('/api/firewall/service','POST',{enabled});await refresh();});
setInterval(()=>{if(state && $('forward-form').hidden && $('host-form').hidden && $('firewall-form').hidden && $('host-config').hidden && $('website-form').hidden && $('dns-form').hidden && $('key-form').hidden)refresh().catch(()=>{});},60000);

function renderServices(){
  const services=state.services;
  $('website-status').textContent=state.mode==='preview'?'Preview · websites are saved without changing Caddy.':!services.webEnabled?'Caddy backend is disabled. Complete website setup on the VPS.':services.webRunning?'Caddy is running · '+(services.staging?'Let’s Encrypt staging (test certificates)':'Let’s Encrypt production'):'Caddy is stopped. Start the backend before applying websites.';
  $('website-list').innerHTML=state.websites.map(r=>{const cert=(services.certificates||[]).find(c=>r.domains.every(d=>c.domains.includes(d)));const ssl=r.ssl?(cert?'Stored certificate expires '+cert.expires:'Certificate pending · requires live Caddy and public DNS'):'HTTP only';return '<article class="card"><div><h3>'+esc(r.name)+' '+badge(r.enabled)+'</h3><p>'+esc(r.domains.join(', '))+'</p><p>'+esc(r.scheme.toUpperCase())+' → '+esc(r.hostId==='@vps'?'This VPS':r.hostId)+' :'+r.port+'</p><p>'+esc(ssl)+'</p></div><div class="actions"><button data-website-action="edit" data-id="'+esc(r.id)+'">Edit</button><button role="switch" aria-checked="'+r.enabled+'" data-website-action="toggle" data-id="'+esc(r.id)+'">'+(r.enabled?'On':'Off')+'</button><button data-website-action="delete" data-id="'+esc(r.id)+'">Remove</button></div></article>';}).join('')||empty('Add a domain and choose its tunnel host to start.');
  $('dns-status').textContent=state.mode==='preview'?'Preview · DNS records are saved without changing the DNS server.':!services.dnsEnabled?'DNS backend is disabled. Complete DNS setup on the VPS.':services.dnsRunning?'Authoritative DNS server is running.':'DNS backend is stopped.';
  const rows=(services.nameservers||[]).map(ns=>['A (DNS only)',ns,services.publicIP||'YOUR_VPS_IP']);for(const zone of services.zones||[])for(const ns of services.nameservers||[])rows.push(['NS',zone,ns]);
  $('dns-delegation').innerHTML='<table><thead><tr><th>Type</th><th>Name in Cloudflare</th><th>Content</th></tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(c=>'<td>'+esc(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
  $('dns-list').innerHTML=state.dnsRecords.map(r=>'<article class="card"><div><h3>'+esc(r.name)+' '+badge(r.enabled)+'</h3><p>'+esc(r.type)+' · '+esc(r.content)+' · TTL '+r.ttl+'</p></div><div class="actions"><button data-dns-action="edit" data-id="'+esc(r.id)+'">Edit</button><button role="switch" aria-checked="'+r.enabled+'" data-dns-action="toggle" data-id="'+esc(r.id)+'">'+(r.enabled?'On':'Off')+'</button><button data-dns-action="delete" data-id="'+esc(r.id)+'">Remove</button></div></article>').join('')||empty('No custom DNS records yet. Zone SOA and nameserver records are managed automatically.');
  $('legacy-dns').innerHTML=state.forwards.filter(f=>f.dnsRecordId).map(f=>'<article class="card"><div><h3>Existing Cloudflare record</h3><p>'+esc(f.hostname)+' · associated with '+esc(f.name||f.id)+'</p></div><button data-legacy-dns="'+esc(f.id)+'">Remove DNS record</button></article>').join('');
}
function editWebsite(rule){const f=$('website-form');f.reset();f.elements.id.value='';f.hidden=false;f.elements.hostId.innerHTML='<option value="@vps">This VPS · 127.0.0.1</option>'+state.hosts.map(h=>'<option value="'+esc(h.id)+'">'+esc(h.id)+' · '+esc(h.address)+'</option>').join('');if(rule)for(const [k,v] of Object.entries(rule))if(f.elements[k]){if(k==='ssl'||k==='enabled')f.elements[k].checked=v;else f.elements[k].value=k==='domains'?v.join(', '):v;}f.scrollIntoView({behavior:'smooth',block:'center'});}
$('new-website').onclick=()=>editWebsite();$('cancel-website').onclick=()=>$('website-form').hidden=true;
$('website-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const body=Object.fromEntries(new FormData(f));body.domains=body.domains.split(/[\s,]+/).filter(Boolean);body.port=Number(body.port);body.ssl=f.elements.ssl.checked;body.enabled=f.elements.enabled.checked;await request('/api/websites','POST',body);f.hidden=true;await refresh();});};
$('website-list').onclick=e=>attempt(async()=>{const button=e.target.closest('[data-website-action]');if(!button)return;const r=state.websites.find(r=>r.id===button.dataset.id);if(button.dataset.websiteAction==='edit')return editWebsite(r);if(button.dataset.websiteAction==='toggle')await request('/api/websites','POST',{...r,enabled:!r.enabled});else{if(!confirm('Remove website '+r.name+'?'))return;await request('/api/websites/'+encodeURIComponent(r.id),'DELETE');}await refresh();});
function dnsHelp(){const type=$('dns-type').value;$('dns-content-help').textContent={A:'IPv4 address, normally your VPS public IP.',AAAA:'IPv6 address. Use only if the VPS and service support public IPv6.',CNAME:'Full target domain, for example another.minecraft.mrhaydenn.us.',TXT:'Enter the text without surrounding quotation marks.',SRV:'priority weight port target — for example: 0 5 20080 trigun.minecraft.mrhaydenn.us'}[type];}
function editDNS(rule){const f=$('dns-form');f.reset();f.elements.id.value='';f.hidden=false;f.elements.zone.innerHTML=(state.services.zones||[]).map(z=>'<option>'+esc(z)+'</option>').join('');if(rule)for(const [k,v] of Object.entries(rule))if(f.elements[k]){if(k==='enabled')f.elements[k].checked=v;else f.elements[k].value=v;}dnsHelp();f.scrollIntoView({behavior:'smooth',block:'center'});}
$('new-dns').onclick=()=>editDNS();$('cancel-dns').onclick=()=>$('dns-form').hidden=true;$('dns-type').onchange=dnsHelp;
$('dns-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const body=Object.fromEntries(new FormData(f));body.ttl=Number(body.ttl);body.enabled=f.elements.enabled.checked;await request('/api/dns-records','POST',body);f.hidden=true;await refresh();});};
$('dns-list').onclick=e=>attempt(async()=>{const button=e.target.closest('[data-dns-action]');if(!button)return;const r=state.dnsRecords.find(r=>r.id===button.dataset.id);if(button.dataset.dnsAction==='edit')return editDNS(r);if(button.dataset.dnsAction==='toggle')await request('/api/dns-records','POST',{...r,enabled:!r.enabled});else{if(!confirm('Remove DNS record '+r.name+'?'))return;await request('/api/dns-records/'+encodeURIComponent(r.id),'DELETE');}await refresh();});
$('apply-websites').onclick=()=>attempt(async()=>{await request('/api/websites/apply','POST',{});await refresh();notice(state.mode==='preview'?'Preview: saved websites were not applied.':'Saved websites applied. Certificate issuance runs automatically; refresh for status.');});
$('apply-dns').onclick=()=>attempt(async()=>{await request('/api/dns-records/apply','POST',{});await refresh();notice(state.mode==='preview'?'Preview: saved DNS records were not applied.':'Saved DNS records applied.');});
$('legacy-dns').onclick=e=>attempt(async()=>{const button=e.target.closest('[data-legacy-dns]');if(!button||!confirm('Remove this existing Cloudflare DNS record?'))return;await request(endpoint(button.dataset.legacyDns)+'/dns','DELETE');await refresh();});

function clearKey() { $('key-token').value=''; $('key-secret').hidden=true; }
function showKey(result) { clearKey(); $('key-token').value=result.token; $('key-secret').hidden=false; $('key-secret').scrollIntoView({behavior:'smooth',block:'center'}); }
function renderIntegrationKeys() {
  $('new-key').disabled=!(state.services.zones||[]).length;
  $('key-list').innerHTML=(state.integrationKeys||[]).map(k=>'<article class="card"><div><h3>'+esc(k.name)+'</h3><p>DNS publishing · '+esc(k.zone)+'</p></div><div class="actions"><button data-key-action="rename" data-id="'+esc(k.id)+'">Rename</button><button data-key-action="rotate" data-id="'+esc(k.id)+'">Rotate</button><button data-key-action="revoke" data-id="'+esc(k.id)+'">Revoke</button></div></article>').join('')||empty('No integration keys. Generate a named key for MMSM.');
}
$('new-key').onclick=()=>{clearKey();const f=$('key-form');f.reset();f.elements.zone.innerHTML=(state.services.zones||[]).map(z=>'<option>'+esc(z)+'</option>').join('');f.hidden=false;};
$('cancel-key').onclick=()=>$('key-form').hidden=true;
$('key-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const f=e.target;const button=f.querySelector('button');button.disabled=true;try{const result=await request('/api/integration-keys','POST',Object.fromEntries(new FormData(f)));f.hidden=true;showKey(result);await refresh();}finally{button.disabled=false;}});};
$('clear-key').onclick=clearKey;
$('copy-key').onclick=async()=>{try{await navigator.clipboard.writeText($('key-token').value);notice('Token copied. Paste it into MMSM and save settings.');}catch(error){$('key-token').focus();$('key-token').select();notice('Press Ctrl+C to copy the selected token.');}};
$('key-list').onclick=e=>attempt(async()=>{const b=e.target.closest('[data-key-action]');if(!b)return;const key=state.integrationKeys.find(k=>k.id===b.dataset.id);const path='/api/integration-keys/'+encodeURIComponent(key.id);const action=b.dataset.keyAction;if(action==='rename'){const name=prompt('Key name',key.name);if(name===null)return;await request(path,'PUT',{name});}else if(action==='rotate'){if(!confirm('Replace the token for '+key.name+'? Update MMSM with the new token. Existing DNS records keep their ownership.'))return;showKey(await request(path+'/rotate','POST',{}));}else{if(!confirm('Revoke '+key.name+'? Its token will stop working. Existing DNS records remain published.'))return;await request(path,'DELETE');clearKey();}await refresh();});

async function updateStatus(){const status=await request('/api/update');$('update-status').textContent=status.active?'Update is running. UNM may briefly disconnect; sign in again after restart.':'Installed commit '+status.revision+(status.result==='exit-code'?' · Last update failed; inspect journalctl -u unm-update':'');$('run-update').disabled=status.active;}
$('check-update').onclick=()=>attempt(updateStatus);
$('run-update').onclick=()=>attempt(async()=>{if(!confirm('Update UNM from the latest GitHub main push? A backup is created and the panel restarts.'))return;await request('/api/update','POST',{});$('run-update').disabled=true;$('update-status').textContent='Update started. Wait for UNM to restart, then reload and sign in again.';});
$('provisioning-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{await request('/api/wireguard/provisioning','POST',Object.fromEntries(new FormData(e.target)));await refresh();notice('WireGuard peer provisioning enabled. Existing tunnels remain in place.');});};
document.querySelector('[data-tab="settings"]').addEventListener('click',()=>{const f=$('provisioning-form');f.elements.endpoint.value=state.wireguard.available?state.wireguard.endpoint:state.services.publicIP?state.services.publicIP+':51820':'';attempt(updateStatus);});
