const state={
  baseUrl:localStorage.getItem('openmiura.baseUrl')||`${location.origin}/broker`,
  token:localStorage.getItem('openmiura.token')||'',
  authMode:localStorage.getItem('openmiura.authMode')||'token',
  username:localStorage.getItem('openmiura.username')||'',
  currentSessionId:null,
  currentCanvasId:null,
  agents:[],
  me:null,
  liveAbort:null,
  builderCatalog:[],
  deferredInstallPrompt:null,
  serviceWorkerReady:false,
  channelWizard:null,
  secretEnvWizard:null,
  reloadAssistant:null,
};
const $=id=>document.getElementById(id);
const authHeader=()=>state.token?{Authorization:`Bearer ${state.token}`}:{ };
const jsonHeaders=()=>({'Content-Type':'application/json',...authHeader()});
const isAdminLike=()=>!!(state.me && (state.me.role==='admin' || state.me.role==='operator' || state.me.auth_mode==='broker-token'));

async function api(path,options={}){
  const res=await fetch(`${state.baseUrl}${path}`,{...options,headers:{...jsonHeaders(),...(options.headers||{})}});
  const text=await res.text();
  let data={};
  try{data=text?JSON.parse(text):{}}catch{data={raw:text}};
  if(!res.ok) throw new Error(data.detail||data.error||text||`HTTP ${res.status}`);
  return data;
}
function setStatus(msg,kind='muted'){ $('statusLine').innerHTML=`<span class="${kind}">${msg}</span>`; }
function bindAuthMode(){ const login=state.authMode==='login'; $('loginFields').classList.toggle('hidden',!login); $('tokenFields').classList.toggle('hidden',login); }
function switchTab(name){ document.querySelectorAll('.tab').forEach(el=>el.classList.remove('active','hidden')); document.querySelectorAll('.tab-btn').forEach(el=>el.classList.remove('active')); $(`${name}Tab`).classList.add('active'); document.querySelector(`.tab-btn[data-tab="${name}"]`).classList.add('active'); document.querySelectorAll('.tab').forEach(el=>{ if(!el.classList.contains('active')) el.classList.add('hidden');}); }
function clearChat(){ $('chatLog').innerHTML=''; }
function addChat(role,content,pending=false){ const div=document.createElement('div'); div.className=`msg ${role}${pending?' pending':''}`; div.textContent=content; $('chatLog').appendChild(div); $('chatLog').scrollTop=$('chatLog').scrollHeight; return div; }
function renderCards(boxId, items, mapFn){ const box=$(boxId); box.innerHTML=''; for(const item of items){ const div=document.createElement('div'); div.className='card'; div.innerHTML=mapFn(item); box.appendChild(div);} }
function renderSessions(items){ renderCards('sessionList', items, item=>`<strong>${item.session_id}</strong><small>${item.channel} · ${item.user_id}</small><small>${item.last_message?`${item.last_message.role}: ${item.last_message.content}`:'No messages yet'}</small>`); [...$('sessionList').children].forEach((div,idx)=>div.onclick=()=>{ state.currentSessionId=items[idx].session_id; $('chatSessionLabel').textContent=state.currentSessionId; refreshHistory(); refreshToolCalls(); reconnectLive(); }); }
function renderAgents(items){ const sel=$('agentSelect'); sel.innerHTML=''; for(const item of items){ const opt=document.createElement('option'); opt.value=item.agent_id; opt.textContent=`${item.agent_id}${item.skills?.length?` · ${item.skills.join(',')}`:''}`; sel.appendChild(opt);} }
function renderPending(items){ const box=$('pendingList'); box.innerHTML=''; for(const item of items){ const div=document.createElement('div'); div.className='card'; div.innerHTML=`<strong>${item.tool_name}</strong><small>${item.session_id}</small><small>${JSON.stringify(item.args||{})}</small>`; const row=document.createElement('div'); row.className='row'; const ok=document.createElement('button'); ok.textContent='Confirm'; ok.onclick=async()=>{ await api(`/confirmations/${encodeURIComponent(item.session_id)}/confirm`,{method:'POST',body:JSON.stringify({confirmed:true})}); await refreshPending(); await refreshHistory(); await refreshToolCalls();}; const no=document.createElement('button'); no.className='ghost'; no.textContent='Cancel'; no.onclick=async()=>{ await api(`/confirmations/${encodeURIComponent(item.session_id)}/cancel`,{method:'POST'}); await refreshPending();}; row.append(ok,no); div.appendChild(row); box.appendChild(div);} }
function renderOverview(boxId, items){ const box=$(boxId); box.innerHTML=''; for(const [label,val] of items){ const div=document.createElement('div'); div.className='overview-item'; div.innerHTML=`<small>${label}</small><strong>${val}</strong>`; box.appendChild(div);} }
function appendLiveEvent(type, data){ const box=$('liveEventsBox'); const div=document.createElement('div'); div.className='card'; div.innerHTML=`<strong>${type}</strong><small>${new Date((data.ts||Date.now()/1000)*1000).toLocaleString()}</small><div>${JSON.stringify(data)}</div>`; box.prepend(div); while(box.children.length>40) box.removeChild(box.lastChild); }
function setAuthBadge(me){ state.me=me; $('meBadge').textContent = me ? `${me.auth_mode}${me.username?` · ${me.username}`:''}${me.role?` (${me.role})`:''}` : 'Not authenticated'; $('permBadge').textContent = me?.permissions?.length?`Permissions: ${me.permissions.join(', ')}`:''; const admin=isAdminLike(); $('adminRefreshBtn').disabled=!admin; document.querySelector('.tab-btn[data-tab="admin"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="policies"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="secrets"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="replay"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="operator"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="releases"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="voice"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="tinyRuntime"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="app"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="canvas"]').disabled=!admin; document.querySelector('.tab-btn[data-tab="config"]').disabled=!admin; if(!admin && ($('adminTab').classList.contains('active') || $('policiesTab').classList.contains('active') || $('secretsTab').classList.contains('active') || $('replayTab').classList.contains('active') || $('operatorTab').classList.contains('active') || $('releasesTab').classList.contains('active') || $('voiceTab').classList.contains('active') || $('tinyRuntimeTab').classList.contains('active') || $('appTab').classList.contains('active') || $('canvasTab').classList.contains('active') || $('configTab').classList.contains('active'))) switchTab('workspace'); }

async function connect(){
  state.baseUrl=$('baseUrl').value.replace(/\/$/,'');
  state.authMode=$('authModeSelect').value;
  state.username=$('username').value.trim();
  localStorage.setItem('openmiura.baseUrl',state.baseUrl); localStorage.setItem('openmiura.authMode',state.authMode); localStorage.setItem('openmiura.username',state.username);
  try{
    if(state.authMode==='login'){
      const login=await fetch(`${state.baseUrl}/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value.trim(),password:$('password').value})});
      const loginData=await login.json();
      if(!login.ok) throw new Error(loginData.detail||'Login failed');
      state.token=loginData.token;
      $('token').value=state.token;
    }else state.token=$('token').value.trim();
    localStorage.setItem('openmiura.token',state.token);
    const me=await api('/auth/me');
    setAuthBadge(me); $('connectStatus').innerHTML='<span class="ok">Connected</span>'; setStatus('Connected','ok');
    await Promise.all([refreshAgents(),refreshSessions(),refreshMetrics(),refreshPending(),refreshAdmin(),refreshToolCalls()]);
    await refreshBuilderCatalog().catch(()=>{});
    await refreshPolicyExplorerSnapshot().catch(()=>{});
    await refreshSecretGovernance().catch(()=>{});
    await refreshOperatorConsole().catch(()=>{});
    await refreshTinyRuntimeConsole().catch(()=>{});
    await refreshAppFoundation().catch(()=>{});
    await refreshCanvasCore().catch(()=>{});
    await refreshConfigCenter().catch(()=>{});
    reconnectLive();
  }catch(err){ $('connectStatus').innerHTML=`<span class="danger">${err.message}</span>`; setStatus(err.message,'danger'); }
}
async function logout(){ if(state.liveAbort) state.liveAbort.abort(); if(state.me?.auth_mode==='auth-session'){ try{ await api('/auth/logout',{method:'POST'});}catch{} } state.token=''; localStorage.removeItem('openmiura.token'); $('token').value=''; setAuthBadge(null); $('connectStatus').textContent='Logged out'; }
async function refreshAgents(){ const data=await api('/agents'); state.agents=data.items||[]; renderAgents(state.agents); }
async function refreshSessions(){ const data=await api('/sessions'); renderSessions(data.items||[]); }
async function refreshHistory(){ if(!state.currentSessionId)return; const data=await api(`/sessions/${encodeURIComponent(state.currentSessionId)}/messages`); renderCards('historyBox', data.items||[], item=>`<strong>${item.role}</strong><small>${new Date(item.ts*1000).toLocaleString()}</small><div>${item.content}</div>`); }
async function refreshPending(){ const data=await api('/confirmations'); renderPending(data.items||[]); }
async function refreshMetrics(){ const data=await api('/metrics/summary'); $('metricsBox').textContent=JSON.stringify(data,null,2); }
async function memorySearch(){ const q=$('memoryQuery').value.trim(); if(!q)return; const user=$('memoryUserKey').value.trim(); const qs=new URLSearchParams({q}); if(user)qs.set('user_key',user); const data=await api(`/memory/search?${qs.toString()}`); renderCards('memoryResults',data.items||[], item=>`<strong>${item.kind||'memory'}</strong><small>score: ${item.score??''} · tier: ${item.tier??''}</small><div>${item.text}</div>`); }
async function refreshToolCalls(){ const qs = new URLSearchParams(); if(state.currentSessionId) qs.set('session_id', state.currentSessionId); const data=await api(`/tool-calls${qs.toString()?`?${qs.toString()}`:''}`); renderCards('toolCallsBox', data.items||[], item=>`<strong>${item.tool_name}</strong><small>${item.agent_id} · ${item.ok?'ok':'error'} · ${Math.round(item.duration_ms)} ms</small><small>${new Date(item.ts*1000).toLocaleString()}</small><div>${JSON.stringify(item.args||{})}</div><div>${item.result_excerpt||item.error||''}</div>`); }


function renderConfigFileCards(sections){
  renderCards('configFileList', sections||[], item=>`<strong>${item.title}</strong><small>${item.path}</small><small>${item.exists?'present':'missing'} · ${item.reload_supported?'live reload':'save only'}${item.restart_required?' · restart required':''}</small><div>${JSON.stringify(item.summary||{})}</div>`);
  [...$('configFileList').children].forEach((div,idx)=>div.onclick=()=>selectConfigSection((sections||[])[idx]?.name));
}

function selectedReloadAssistantSections(){
  return [...document.querySelectorAll('[data-reload-assistant-section]')].filter(el=>el.checked).map(el=>el.dataset.reloadAssistantSection||'').filter(Boolean);
}

function persistReloadAssistantSections(){
  localStorage.setItem('openmiura.reloadAssistantSections', JSON.stringify(selectedReloadAssistantSections()));
}

function renderReloadAssistant(snapshot){
  state.reloadAssistant=snapshot||{sections:[],recent_restart_requests:[],restart_hook:{},operational_state:{}};
  const remembered=new Set((()=>{ try{return JSON.parse(localStorage.getItem('openmiura.reloadAssistantSections')||'[]')}catch{return []} })());
  const list=$('reloadAssistantSectionList');
  list.innerHTML='';
  const autoSelect=!remembered.size;
  for(const item of (state.reloadAssistant.sections||[])){
    const card=document.createElement('label');
    card.className='card';
    const checked=remembered.has(item.name) || (autoSelect && (item.reload_supported || item.restart_required));
    const validity=item.valid===false?' · invalid YAML':'';
    const presence=item.exists?'present':'missing';
    card.innerHTML=`<div class="row between wrap"><span class="row wrap"><input type="checkbox" data-reload-assistant-section="${item.name}" ${checked?'checked':''} /><strong>${item.title||item.name}</strong></span><span class="muted">${presence} · ${item.reload_supported?'live reload':'save only'}${item.restart_required?' · restart required':''}${validity}</span></div><small>${item.path||''}</small><div>${JSON.stringify(item.summary||{})}</div>`;
    list.appendChild(card);
  }
  document.querySelectorAll('[data-reload-assistant-section]').forEach(el=>el.onchange=()=>persistReloadAssistantSections());
  persistReloadAssistantSections();
  const hook=state.reloadAssistant.restart_hook||{};
  $('reloadAssistantHookBadge').textContent=hook.configured?`External restart hook configured${hook.command_preview?` · ${hook.command_preview}`:''}`:(hook.allow_self_restart?'Self restart allowed but hook command missing':'External restart hook not configured');
  $('reloadAssistantExecuteHook').disabled=!hook.configured;
  if(!hook.configured) $('reloadAssistantExecuteHook').checked=false;
  const operational=state.reloadAssistant.operational_state||{};
  const health=operational.health||{};
  const process=operational.process||{};
  const restartObservation=operational.restart_observation||{};
  const hookResult=operational.restart_hook_result||{};
  const bootEvidence=operational.latest_boot_evidence||{};
  const currentBoot=operational.current_boot||{};
  $('reloadAssistantRuntimeBadge').textContent=`${health.status||'unknown'}${process.pid?` · PID ${process.pid}`:''}${process.uptime_human?` · uptime ${process.uptime_human}`:''}${restartObservation.state?` · restart ${restartObservation.state}`:''}`;
  $('reloadAssistantRuntimeBox').textContent=pretty({health,process,restart_observation:restartObservation,current_boot:currentBoot});
  $('reloadAssistantStartupConfigBox').textContent=pretty(operational.startup_config||{});
  $('reloadAssistantHookResultBadge').textContent=hookResult.available?(hookResult.ok?'Hook succeeded':(hookResult.executed?'Hook failed':'Hook not executed')):'No hook result';
  $('reloadAssistantHookResultBox').textContent=pretty(hookResult);
  $('reloadAssistantBootEvidenceBadge').textContent=`${bootEvidence.current_process_matches?'Current boot active':'Boot evidence differs'}${bootEvidence.boot_instance_id?` · ${bootEvidence.boot_instance_id}`:''}`;
  $('reloadAssistantBootEvidenceBox').textContent=pretty(bootEvidence);
  renderCards('reloadAssistantRecentList', state.reloadAssistant.recent_restart_requests||[], item=>{
    const hookState=item.execute_restart_hook?(item.hook_ok?'hook ok':'hook pending/failed'):'hook skipped';
    return `<strong>${item.request_id||'restart-request'}</strong><small>${new Date((item.ts||0)*1000).toLocaleString()}</small><small>${item.status||'queued'} · ${(item.sections||[]).join(', ')||'no sections'} · ${hookState}</small><div>${item.actor||''}${item.execute_restart_hook?' · hook requested':''}</div>`;
  });
}

function tinyRuntimeScopeParams(){
  const qs=new URLSearchParams();
  const tenant=($('tinyRuntimeTenant')?.value||$('appTenant')?.value||'').trim();
  const workspace=($('tinyRuntimeWorkspace')?.value||$('appWorkspace')?.value||'').trim();
  const environment=($('tinyRuntimeEnvironment')?.value||$('appEnvironment')?.value||'').trim();
  const status=($('tinyRuntimeFilterStatus')?.value||'').trim();
  const kind=($('tinyRuntimeFilterKind')?.value||'').trim().toLowerCase();
  if(tenant) qs.set('tenant_id',tenant);
  if(workspace) qs.set('workspace_id',workspace);
  if(environment) qs.set('environment',environment);
  if(status) qs.set('status',status);
  return {qs, kind, tenant, workspace, environment};
}

async function refreshTinyRuntimeConsole(){
  if(!isAdminLike() || !document.getElementById('tinyRuntimeList')) return;
  const {qs,kind,tenant,workspace,environment}=tinyRuntimeScopeParams();
  const suffix=qs.toString()?`?${qs.toString()}`:'';
  const data=await api(`/admin/openclaw/runtimes${suffix}`);
  const items=(data.items||[]).filter(item=>!kind || String(item?.metadata?.kind||'').toLowerCase()===kind || String(item?.transport||'').toLowerCase()==='simulated');
  $('tinyRuntimeOverview').innerHTML='';
  renderOverview('tinyRuntimeOverview',[
    ['count', items.length],
    ['tenant', tenant||'—'],
    ['workspace', workspace||'—'],
    ['environment', environment||'—'],
  ]);
  $('tinyRuntimeListSummary').textContent=`${items.length} runtime(s)`;
  $('tinyRuntimeConsoleBox').textContent=pretty({summary:data.summary||{},scope:{tenant_id:tenant||null,workspace_id:workspace||null,environment:environment||null},kind_filter:kind||null,items:items.map(item=>({runtime_id:item.runtime_id,name:item.name,status:item.status,kind:item.metadata?.kind,runtime_class:item.metadata?.runtime_class,policy_pack:item.metadata?.policy_pack}))});
  renderCards('tinyRuntimeList', items, item=>`<strong>${item.name||item.runtime_id}</strong><small>${item.runtime_id}</small><small>${item.status||'registered'} · ${item.transport||'http'} · ${(item.metadata&&item.metadata.kind)||'unknown kind'}</small><div>${(item.metadata&&item.metadata.runtime_class)||''}${item.metadata?.policy_pack?` · pack ${item.metadata.policy_pack}`:''}</div>`);
  [...$('tinyRuntimeList').children].forEach((div,idx)=>div.onclick=()=>loadTinyRuntimeDetail(items[idx].runtime_id));
  if(items.length){
    const selected=$('tinyRuntimeSelectedBadge').dataset.runtimeId||'';
    const target=items.some(item=>item.runtime_id===selected)?selected:items[0].runtime_id;
    await loadTinyRuntimeDetail(target);
  } else {
    $('tinyRuntimeSelectedBadge').dataset.runtimeId='';
    $('tinyRuntimeSelectedBadge').textContent='No runtime selected';
    $('tinyRuntimeDetailBadge').textContent='No runtime selected';
    $('tinyRuntimeDetailBox').textContent='';
    $('tinyRuntimeDispatchSummaryBox').textContent='';
    $('tinyRuntimeDispatchList').innerHTML='';
  }
  return data;
}

async function loadTinyRuntimeDetail(runtimeId){
  if(!runtimeId || !document.getElementById('tinyRuntimeDetailBox')) return null;
  const {qs}=tinyRuntimeScopeParams();
  const suffix=qs.toString()?`?${qs.toString()}`:'';
  const data=await api(`/admin/openclaw/runtimes/${encodeURIComponent(runtimeId)}${suffix}`);
  const runtime=data.runtime||{};
  const summary=data.runtime_summary||{};
  $('tinyRuntimeSelectedBadge').dataset.runtimeId=runtimeId;
  $('tinyRuntimeSelectedBadge').textContent=runtime.name||runtimeId;
  $('tinyRuntimeDetailBadge').textContent=`${runtime.status||'registered'}${summary?.metadata?.kind?` · ${summary.metadata.kind}`:''}${summary?.metadata?.runtime_class?` · ${summary.metadata.runtime_class}`:''}`;
  $('tinyRuntimeDispatchSummaryBox').textContent=pretty({dispatch_summary:data.dispatch_summary||{},health:data.health||{}});
  $('tinyRuntimeDetailBox').textContent=pretty({runtime, runtime_summary:summary, health:data.health||{}, available_actions:data.available_actions||[]});
  renderCards('tinyRuntimeDispatchList', data.dispatches||[], item=>`<strong>${item.action||'dispatch'}</strong><small>${item.dispatch_id||''}</small><small>${item.canonical_status||item.status||'unknown'}</small><div>${item.result_excerpt||item.error||''}</div>`);
  return data;
}

function renderConfigForm(file){
  const box=$('configFormGroups');
  const unavailable=$('configFormUnavailable');
  box.innerHTML='';
  const enabled=!!(file && file.section==='openmiura' && file.form_schema && file.form_values);
  unavailable.classList.toggle('hidden', enabled);
  if(!enabled){ $('configFormPreviewBox').textContent=''; return; }
  const allFields=(file.form_schema||[]).flatMap(group=>group.fields||[]);
  for(const group of (file.form_schema||[])){
    const section=document.createElement('section');
    section.className='config-form-group stack';
    const title=document.createElement('h4');
    title.textContent=group.group;
    section.appendChild(title);
    const grid=document.createElement('div');
    grid.className='config-form-grid';
    for(const field of (group.fields||[])){
      const row=document.createElement('div');
      row.className=`config-form-field ${field.type==='bool'?'bool':''}`;
      const safeId=`configForm__${String(field.name||'').replace(/[^a-zA-Z0-9_]+/g,'_')}`;
      if(field.type==='bool'){
        row.innerHTML=`<label><input type="checkbox" id="${safeId}" data-config-form-name="${field.name}" data-config-form-type="${field.type}" /> ${field.label}</label>`;
      }else if(field.type==='select'){
        const options=(field.options||[]).map(opt=>`<option value="${opt}">${opt}</option>`).join('');
        row.innerHTML=`<label for="${safeId}">${field.label}</label><select id="${safeId}" data-config-form-name="${field.name}" data-config-form-type="${field.type}">${options}</select>`;
      }else{
        const inputType=field.type==='int' || field.type==='float' ? 'number' : 'text';
        const attrs=[];
        if(field.min!==undefined) attrs.push(`min="${field.min}"`);
        if(field.step!==undefined) attrs.push(`step="${field.step}"`);
        if(field.placeholder) attrs.push(`placeholder="${field.placeholder}"`);
        row.innerHTML=`<label for="${safeId}">${field.label}</label><input type="${inputType}" id="${safeId}" data-config-form-name="${field.name}" data-config-form-type="${field.type}" ${attrs.join(' ')} />`;
      }
      grid.appendChild(row);
    }
    section.appendChild(grid);
    box.appendChild(section);
  }
  setConfigFormValues(file.form_values||{});
  $('configFormPreviewBox').textContent=file.raw||'';
}

function renderChannelWizard(snapshot){
  state.channelWizard=snapshot||{schemas:{},values:{},channels:[]};
  const select=$('channelWizardChannelSelect');
  const previous=select.value||localStorage.getItem('openmiura.channelWizardChannel')||'telegram';
  select.innerHTML='';
  for(const item of state.channelWizard.channels||[]){ const opt=document.createElement('option'); opt.value=item.name; opt.textContent=item.title||item.name; select.appendChild(opt); }
  if([...select.options].some(opt=>opt.value===previous)) select.value=previous;
  if(select.value) selectChannelWizardChannel(select.value,state.channelWizard);
}

function selectChannelWizardChannel(channel,snapshot){
  const data=snapshot||state.channelWizard||{schemas:{},values:{},channels:[]};
  if(!channel) return;
  $('channelWizardChannelSelect').value=channel;
  localStorage.setItem('openmiura.channelWizardChannel',channel);
  const groups=data.schemas?.[channel]||[];
  const values=data.values?.[channel]||{};
  const status=(data.channels||[]).find(item=>item.name===channel)?.status||{};
  const box=$('channelWizardGroups');
  box.innerHTML='';
  for(const group of groups){
    const section=document.createElement('section');
    section.className='config-form-group stack';
    const title=document.createElement('h4');
    title.textContent=group.group;
    section.appendChild(title);
    const grid=document.createElement('div');
    grid.className='config-form-grid';
    for(const field of (group.fields||[])){
      const row=document.createElement('div');
      row.className=`config-form-field ${field.type==='bool'?'bool':''}`;
      const safeId=`channelWizard__${String(field.name||'').replace(/[^a-zA-Z0-9_]+/g,'_')}`;
      if(field.type==='bool'){
        row.innerHTML=`<label><input type="checkbox" id="${safeId}" data-channel-wizard-name="${field.name}" data-channel-wizard-type="${field.type}" /> ${field.label}</label>`;
      }else if(field.type==='select'){
        const options=(field.options||[]).map(opt=>`<option value="${opt}">${opt}</option>`).join('');
        row.innerHTML=`<label for="${safeId}">${field.label}</label><select id="${safeId}" data-channel-wizard-name="${field.name}" data-channel-wizard-type="${field.type}">${options}</select>`;
      }else{
        const inputType=field.type==='int' || field.type==='float' ? 'number' : 'text';
        const attrs=[];
        if(field.min!==undefined) attrs.push(`min="${field.min}"`);
        if(field.step!==undefined) attrs.push(`step="${field.step}"`);
        if(field.placeholder) attrs.push(`placeholder="${field.placeholder}"`);
        row.innerHTML=`<label for="${safeId}">${field.label}</label><input type="${inputType}" id="${safeId}" data-channel-wizard-name="${field.name}" data-channel-wizard-type="${field.type}" ${attrs.join(' ')} />`;
      }
      grid.appendChild(row);
    }
    section.appendChild(grid);
    box.appendChild(section);
  }
  setChannelWizardValues(values);
  $('channelWizardBadge').textContent=`${channel}${status.configured?' · configured':' · not configured'}`;
  $('channelWizardSummaryBox').textContent=pretty(status||{});
  $('channelWizardPreviewBox').textContent=data.raw||$('configEditor').value||'';
}

function secretEnvSuggestionMap(prefix){
  const safe=(prefix||'OPENMIURA').trim().toUpperCase().replace(/[^A-Z0-9_]+/g,'_')||'OPENMIURA';
  return {
    'llm.api_key_env_var': `${safe}_LLM_API_KEY`,
    'telegram.bot_token': `${safe}_TELEGRAM_BOT_TOKEN`,
    'telegram.webhook_secret': `${safe}_TELEGRAM_WEBHOOK_SECRET`,
    'slack.bot_token': `${safe}_SLACK_BOT_TOKEN`,
    'slack.signing_secret': `${safe}_SLACK_SIGNING_SECRET`,
    'discord.bot_token': `${safe}_DISCORD_BOT_TOKEN`,
  };
}

function renderSecretEnvWizard(snapshot){
  state.secretEnvWizard=snapshot||{schemas:{},values:{},profiles:[],suggestions:{},env_prefix:'OPENMIURA'};
  const select=$('secretEnvProfileSelect');
  const previous=select.value||localStorage.getItem('openmiura.secretEnvProfile')||'llm';
  select.innerHTML='';
  for(const item of state.secretEnvWizard.profiles||[]){ const opt=document.createElement('option'); opt.value=item.name; opt.textContent=item.title||item.name; select.appendChild(opt); }
  if(!$('secretEnvPrefixInput').value) $('secretEnvPrefixInput').value=state.secretEnvWizard.env_prefix||'OPENMIURA';
  if([...select.options].some(opt=>opt.value===previous)) select.value=previous;
  if(select.value) selectSecretEnvProfile(select.value,state.secretEnvWizard);
}

function selectSecretEnvProfile(profile,snapshot){
  const data=snapshot||state.secretEnvWizard||{schemas:{},values:{},profiles:[]};
  if(!profile) return;
  $('secretEnvProfileSelect').value=profile;
  localStorage.setItem('openmiura.secretEnvProfile',profile);
  const groups=data.schemas?.[profile]||[];
  const values=data.values?.[profile]||{};
  const status=(data.profiles||[]).find(item=>item.name===profile)?.status||{};
  const box=$('secretEnvGroups');
  box.innerHTML='';
  for(const group of groups){
    const section=document.createElement('section');
    section.className='config-form-group stack';
    const title=document.createElement('h4');
    title.textContent=group.group;
    section.appendChild(title);
    const grid=document.createElement('div');
    grid.className='config-form-grid';
    for(const field of (group.fields||[])){
      const row=document.createElement('div');
      row.className=`config-form-field ${field.type==='bool'?'bool':''}`;
      const safeId=`secretEnvWizard__${String(field.name||'').replace(/[^a-zA-Z0-9_]+/g,'_')}`;
      if(field.type==='bool'){
        row.innerHTML=`<label><input type="checkbox" id="${safeId}" data-secret-env-name="${field.name}" data-secret-env-type="${field.type}" /> ${field.label}</label>`;
      }else if(field.type==='select'){
        const options=(field.options||[]).map(opt=>`<option value="${opt}">${opt}</option>`).join('');
        row.innerHTML=`<label for="${safeId}">${field.label}</label><select id="${safeId}" data-secret-env-name="${field.name}" data-secret-env-type="${field.type}">${options}</select>`;
      }else{
        const inputType=field.type==='int' || field.type==='float' ? 'number' : 'text';
        const attrs=[];
        if(field.min!==undefined) attrs.push(`min="${field.min}"`);
        if(field.step!==undefined) attrs.push(`step="${field.step}"`);
        if(field.placeholder) attrs.push(`placeholder="${field.placeholder}"`);
        row.innerHTML=`<label for="${safeId}">${field.label}</label><input type="${inputType}" id="${safeId}" data-secret-env-name="${field.name}" data-secret-env-type="${field.type}" ${attrs.join(' ')} />`;
      }
      grid.appendChild(row);
    }
    section.appendChild(grid);
    box.appendChild(section);
  }
  setSecretEnvWizardValues(values);
  $('secretEnvBadge').textContent=`${profile}${status.configured?' · configured':' · not configured'}`;
  $('secretEnvSummaryBox').textContent=pretty(status||{});
  $('secretEnvExampleBox').textContent=status.env_example||'';
  $('secretEnvPreviewBox').textContent=data.raw||$('configEditor').value||'';
}

function collectSecretEnvWizardPayload(){
  const payload={};
  document.querySelectorAll('[data-secret-env-name]').forEach(el=>{
    const name=el.dataset.secretEnvName;
    const fieldType=el.dataset.secretEnvType||'string';
    if(fieldType==='bool') payload[name]=!!el.checked;
    else payload[name]=el.value;
  });
  return payload;
}

function setSecretEnvWizardValues(values){
  document.querySelectorAll('[data-secret-env-name]').forEach(el=>{
    const name=el.dataset.secretEnvName;
    const fieldType=el.dataset.secretEnvType||'string';
    const raw=values&&Object.prototype.hasOwnProperty.call(values,name)?values[name]:'';
    if(fieldType==='bool') el.checked=!!raw;
    else el.value=raw ?? '';
  });
}

function applySuggestedSecretEnvRefs(){
  const profile=$('secretEnvProfileSelect').value||'llm';
  const suggestions=secretEnvSuggestionMap($('secretEnvPrefixInput').value||'OPENMIURA');
  document.querySelectorAll('[data-secret-env-name]').forEach(el=>{
    const name=el.dataset.secretEnvName||'';
    if(name.endsWith('.mode')){
      el.value='env';
      return;
    }
    if(name.endsWith('.value')){
      const base=name.slice(0,-6);
      el.value=suggestions[base]||el.value||'';
    }
  });
  $('secretEnvBadge').textContent=`${profile} · suggested env refs ready`;
  setStatus(`Suggested env refs generated for ${profile}`,'ok');
}

async function refreshSecretEnvWizard(snapshotOverride){
  const prefix=($('secretEnvPrefixInput')?.value||'OPENMIURA').trim()||'OPENMIURA';
  const data=snapshotOverride||await api(`/admin/config-center/secrets-wizard?env_prefix=${encodeURIComponent(prefix)}`);
  renderSecretEnvWizard(data);
  return data;
}

async function loadSecretEnvWizardFromEditor(){
  const profile=$('secretEnvProfileSelect').value||'llm';
  const env_prefix=($('secretEnvPrefixInput').value||'OPENMIURA').trim()||'OPENMIURA';
  const data=await api('/admin/config-center/secrets-wizard/validate',{method:'POST',body:JSON.stringify({profile,env_prefix,content:$('configEditor').value})});
  setSecretEnvWizardValues(data.wizard_values||{});
  $('secretEnvPreviewBox').textContent=data.normalized_yaml||'';
  $('secretEnvExampleBox').textContent=data.env_example||'';
  $('secretEnvSummaryBox').textContent=pretty(data.profile_status||{});
  $('secretEnvBadge').textContent=`${profile}${data.profile_status?.configured?' · configured':' · not configured'}`;
  setStatus(`${profile} secret refs loaded from YAML`,'ok');
  return data;
}

async function applySecretEnvWizardToEditor(){
  const profile=$('secretEnvProfileSelect').value||'llm';
  const env_prefix=($('secretEnvPrefixInput').value||'OPENMIURA').trim()||'OPENMIURA';
  const data=await api('/admin/config-center/secrets-wizard/validate',{method:'POST',body:JSON.stringify({profile,env_prefix,content:$('configEditor').value,wizard_payload:collectSecretEnvWizardPayload()})});
  $('configEditor').value=data.normalized_yaml||'';
  $('secretEnvPreviewBox').textContent=data.normalized_yaml||'';
  $('secretEnvExampleBox').textContent=data.env_example||'';
  $('secretEnvSummaryBox').textContent=pretty(data.profile_status||{});
  setSecretEnvWizardValues(data.wizard_values||{});
  setStatus(`${profile} secret refs applied to YAML editor`,'ok');
  return data;
}

async function saveSecretEnvWizard(reloadAfterSave){
  const profile=$('secretEnvProfileSelect').value||'llm';
  const env_prefix=($('secretEnvPrefixInput').value||'OPENMIURA').trim()||'OPENMIURA';
  const data=await api('/admin/config-center/secrets-wizard/save',{method:'POST',body:JSON.stringify({profile,env_prefix,content:$('configEditor').value,wizard_payload:collectSecretEnvWizardPayload(),reload_after_save:reloadAfterSave || $('configReloadToggle').checked})});
  $('configSaveResultBox').textContent=pretty(data);
  $('configEditor').value=data.secret_env_validation?.normalized_yaml||data.snapshot?.raw||$('configEditor').value;
  $('secretEnvPreviewBox').textContent=data.secret_env_validation?.normalized_yaml||$('configEditor').value;
  $('secretEnvExampleBox').textContent=data.env_example||'';
  $('secretEnvSummaryBox').textContent=pretty(data.profile_status||{});
  await refreshConfigCenter().catch(()=>{});
  if(state.secretEnvWizard) selectSecretEnvProfile(profile,state.secretEnvWizard);
  const msg=data.restart_required?`Saved ${profile} secret refs. Restart required for full effect.`:`Saved ${profile} secret refs${data.reload_applied?' and applied live reload':''}.`;
  setStatus(msg,data.restart_required?'muted':'ok');
  return data;
}

function collectChannelWizardPayload(){
  const payload={};
  document.querySelectorAll('[data-channel-wizard-name]').forEach(el=>{
    const name=el.dataset.channelWizardName;
    const fieldType=el.dataset.channelWizardType||'string';
    if(fieldType==='bool') payload[name]=!!el.checked;
    else payload[name]=el.value;
  });
  return payload;
}

function setChannelWizardValues(values){
  document.querySelectorAll('[data-channel-wizard-name]').forEach(el=>{
    const name=el.dataset.channelWizardName;
    const fieldType=el.dataset.channelWizardType||'string';
    const raw=values&&Object.prototype.hasOwnProperty.call(values,name)?values[name]:'';
    if(fieldType==='bool') el.checked=!!raw;
    else if((fieldType==='csv_int' || fieldType==='csv_str') && Array.isArray(raw)) el.value=raw.join(', ');
    else el.value=raw ?? '';
  });
}

async function refreshChannelWizard(snapshotOverride){
  const data=snapshotOverride||await api('/admin/config-center/channels-wizard');
  renderChannelWizard(data);
  return data;
}

async function loadChannelWizardFromEditor(){
  const channel=$('channelWizardChannelSelect').value||'telegram';
  const data=await api('/admin/config-center/channels-wizard/validate',{method:'POST',body:JSON.stringify({channel,content:$('configEditor').value})});
  setChannelWizardValues(data.wizard_values||{});
  $('channelWizardPreviewBox').textContent=data.normalized_yaml||'';
  $('channelWizardSummaryBox').textContent=pretty(data.channel_status||{});
  $('channelWizardBadge').textContent=`${channel}${data.channel_status?.configured?' · configured':' · not configured'}`;
  setStatus(`${channel} wizard loaded from YAML`,'ok');
  return data;
}

async function applyChannelWizardToEditor(){
  const channel=$('channelWizardChannelSelect').value||'telegram';
  const data=await api('/admin/config-center/channels-wizard/validate',{method:'POST',body:JSON.stringify({channel,content:$('configEditor').value,wizard_payload:collectChannelWizardPayload()})});
  $('configEditor').value=data.normalized_yaml||'';
  $('channelWizardPreviewBox').textContent=data.normalized_yaml||'';
  $('channelWizardSummaryBox').textContent=pretty(data.channel_status||{});
  setChannelWizardValues(data.wizard_values||{});
  setStatus(`${channel} wizard applied to YAML editor`,'ok');
  return data;
}

async function saveChannelWizard(reloadAfterSave){
  const channel=$('channelWizardChannelSelect').value||'telegram';
  const data=await api('/admin/config-center/channels-wizard/save',{method:'POST',body:JSON.stringify({channel,content:$('configEditor').value,wizard_payload:collectChannelWizardPayload(),reload_after_save:reloadAfterSave || $('configReloadToggle').checked})});
  $('configSaveResultBox').textContent=pretty(data);
  $('configEditor').value=data.validation?.normalized_yaml||data.snapshot?.raw||$('configEditor').value;
  $('channelWizardPreviewBox').textContent=data.channel_validation?.normalized_yaml||$('configEditor').value;
  $('channelWizardSummaryBox').textContent=pretty(data.channel_status||{});
  await refreshConfigCenter().catch(()=>{});
  if(state.channelWizard) selectChannelWizardChannel(channel,state.channelWizard);
  const msg=data.restart_required?`Saved ${channel} channel. Restart required for full effect.`:`Saved ${channel} channel${data.reload_applied?' and applied live reload':''}.`;
  setStatus(msg,data.restart_required?'muted':'ok');
  return data;
}

function collectConfigFormPayload(){
  const payload={};
  document.querySelectorAll('[data-config-form-name]').forEach(el=>{
    const name=el.dataset.configFormName;
    const fieldType=el.dataset.configFormType||'string';
    if(fieldType==='bool') payload[name]=!!el.checked;
    else payload[name]=el.value;
  });
  return payload;
}

function setConfigFormValues(values){
  document.querySelectorAll('[data-config-form-name]').forEach(el=>{
    const name=el.dataset.configFormName;
    const value=values&&Object.prototype.hasOwnProperty.call(values,name)?values[name]:'';
    if(el.dataset.configFormType==='bool') el.checked=!!value;
    else el.value=value ?? '';
  });
}

async function loadConfigFormFromEditor(){
  if($('configSectionSelect').value!=='openmiura') throw new Error('The guided form is only available for openmiura.yaml');
  const data=await api('/admin/config-center/validate',{method:'POST',body:JSON.stringify({section:'openmiura',content:$('configEditor').value})});
  $('configValidationBox').textContent=pretty(data);
  $('configSummaryBox').textContent=pretty({summary:data.summary||{}, top_level_keys:data.top_level_keys||[], warnings:data.warnings||[]});
  if(data.form_values) setConfigFormValues(data.form_values);
  $('configFormPreviewBox').textContent=data.normalized_yaml||'';
  setStatus('Main settings form loaded from YAML','ok');
  return data;
}

async function applyConfigFormToEditor(){
  const data=await api('/admin/config-center/validate',{method:'POST',body:JSON.stringify({section:'openmiura',content:'',form_payload:collectConfigFormPayload()})});
  $('configEditor').value=data.normalized_yaml||'';
  $('configValidationBox').textContent=pretty(data);
  $('configSummaryBox').textContent=pretty({summary:data.summary||{}, top_level_keys:data.top_level_keys||[], warnings:data.warnings||[]});
  if(data.form_values) setConfigFormValues(data.form_values);
  $('configFormPreviewBox').textContent=data.normalized_yaml||'';
  setStatus('Main settings form applied to YAML editor','ok');
  return data;
}

async function saveConfigFormCenter(reloadAfterSave){
  const data=await api('/admin/config-center/save',{method:'POST',body:JSON.stringify({section:'openmiura',content:'',form_payload:collectConfigFormPayload(),reload_after_save:reloadAfterSave || $('configReloadToggle').checked})});
  $('configSaveResultBox').textContent=pretty(data);
  $('configEditor').value=data.validation?.normalized_yaml||data.snapshot?.raw||$('configEditor').value;
  $('configFormPreviewBox').textContent=data.validation?.normalized_yaml||$('configFormPreviewBox').textContent;
  await refreshConfigCenter().catch(()=>{});
  selectConfigSection('openmiura');
  const msg=data.restart_required?'Saved openmiura from form. Restart required for full effect.':`Saved openmiura from form${data.reload_applied?' and applied live reload':''}.`;
  setStatus(msg, data.restart_required?'muted':'ok');
  return data;
}

async function refreshReloadAssistant(snapshotOverride){
  const data=snapshotOverride||await api('/admin/config-center/reload-assistant');
  renderReloadAssistant(data);
  return data;
}

async function applyReloadAssistant(){
  const payload={sections:selectedReloadAssistantSections(),apply_live_reload:$('reloadAssistantApplyLiveReload').checked,request_restart:$('reloadAssistantRequestRestart').checked,execute_restart_hook:$('reloadAssistantExecuteHook').checked};
  const data=await api('/admin/config-center/reload-assistant/apply',{method:'POST',body:JSON.stringify(payload)});
  $('reloadAssistantResultBox').textContent=pretty(data);
  await refreshReloadAssistant().catch(()=>{});
  const status=((data.restart_request||{}).status)||'';
  setStatus(data.restart_request?`Reload assistant applied · restart ${status||'queued'}`:`Reload assistant applied${data.live_reload_applied?' with live reload':''}`,(status==='hook_failed')?'danger':'ok');
  return data;
}

async function refreshConfigCenter(){
  if(!isAdminLike()) return;
  const data = await api('/admin/config-center');
  state.configCenter = data;
  const select = $('configSectionSelect');
  const previous = select.value || localStorage.getItem('openmiura.configSection') || 'openmiura';
  select.innerHTML='';
  for(const item of data.sections||[]){ const opt=document.createElement('option'); opt.value=item.name; opt.textContent=`${item.title} · ${item.name}`; select.appendChild(opt); }
  renderConfigFileCards(data.sections||[]);
  $('configQuickSettingsBox').textContent = pretty(data.quick_settings||{});
  if(data.channel_wizard) renderChannelWizard(data.channel_wizard);
  if(data.secret_env_wizard) renderSecretEnvWizard(data.secret_env_wizard);
  if(data.reload_assistant) renderReloadAssistant(data.reload_assistant);
  if([...select.options].some(opt=>opt.value===previous)) select.value = previous;
  if(select.value) selectConfigSection(select.value, data);
  return data;
}

function selectConfigSection(section, payload){
  const data = payload || state.configCenter || {};
  const file = (data.files||{})[section];
  if(!file) return;
  $('configSectionSelect').value = section;
  localStorage.setItem('openmiura.configSection', section);
  $('configEditor').value = file.raw || '';
  $('configFilePath').value = file.path || '';
  $('configSectionBadge').textContent = `${file.title||section} · ${file.valid?'valid YAML':'parse error'}`;
  $('configSummaryBox').textContent = pretty({summary:file.summary||{}, top_level_keys:file.top_level_keys||[], reload_supported:file.reload_supported, restart_required:file.restart_required, parse_error:file.parse_error||''});
  $('configValidationBox').textContent = pretty({path:file.path, exists:file.exists, valid:file.valid, parse_error:file.parse_error||''});
  $('configReloadToggle').checked = !!file.reload_supported;
  renderConfigForm(file);
}

async function validateConfigCenter(){
  const payload = {section:$('configSectionSelect').value, content:$('configEditor').value};
  const data = await api('/admin/config-center/validate', {method:'POST', body:JSON.stringify(payload)});
  $('configValidationBox').textContent = pretty(data);
  $('configSummaryBox').textContent = pretty({summary:data.summary||{}, top_level_keys:data.top_level_keys||[], warnings:data.warnings||[]});
  if(payload.section==='openmiura' && data.form_values){ setConfigFormValues(data.form_values); $('configFormPreviewBox').textContent=data.normalized_yaml||''; }
  setStatus(`Configuration ${payload.section} validated`, 'ok');
  return data;
}

async function saveConfigCenter(reloadAfterSave){
  const payload = {section:$('configSectionSelect').value, content:$('configEditor').value, reload_after_save: reloadAfterSave || $('configReloadToggle').checked};
  const data = await api('/admin/config-center/save', {method:'POST', body:JSON.stringify(payload)});
  $('configSaveResultBox').textContent = pretty(data);
  await refreshConfigCenter().catch(()=>{});
  selectConfigSection(payload.section);
  const msg = data.restart_required ? `Saved ${payload.section}. Restart required for full effect.` : `Saved ${payload.section}${data.reload_applied?' and applied live reload':''}.`;
  setStatus(msg, data.restart_required ? 'muted' : 'ok');
  return data;
}

function pretty(value){ return JSON.stringify(value,null,2); }
function parseJsonInput(text,fallback){ const raw=(text||'').trim(); if(!raw) return fallback; return JSON.parse(raw); }
function renderBuilderValidation(payload){ $('builderValidation').textContent=pretty(payload||{}); const stats=payload?.stats||{}; $('builderGraphStats').textContent=`${stats.step_count||0} steps · ${stats.edge_count||0} edges${(payload?.warnings||[]).length?` · ${(payload.warnings||[]).length} warnings`:''}`; }
function renderBuilderGraph(graph){ const nodeBox=$('builderGraph'); const edgeBox=$('builderEdges'); nodeBox.innerHTML=''; edgeBox.innerHTML=''; const nodes=(graph?.nodes)||[]; const edges=(graph?.edges)||[]; for(const node of nodes){ const div=document.createElement('div'); div.className=`builder-node ${node.kind||'note'}`; const lane=node?.position?.x===1?'right lane':(node?.position?.x===-1?'left lane':'main lane'); div.innerHTML=`<div><div class="builder-kind">${node.kind||'step'}</div><small>${node.id||''}</small></div><div><h4>${node.label||node.id||'step'}</h4><small>${node.subtitle||''}</small></div><div class="builder-lane">${lane}</div>`; nodeBox.appendChild(div); }
 for(const edge of edges){ const div=document.createElement('div'); div.className='builder-edge'; div.innerHTML=`<code>${edge.source||''}</code><span>${edge.label||edge.kind||'next'}</span><code>${edge.target||''}</code>`; edgeBox.appendChild(div); }
 if(!nodes.length){ nodeBox.innerHTML='<div class="muted">No graph loaded.</div>'; }
 if(!edges.length){ edgeBox.innerHTML='<div class="muted">No edges to show.</div>'; }
}
function renderBuilderCatalog(items){ state.builderCatalog=items||[]; $('builderCatalogSummary').textContent=`${state.builderCatalog.length} playbooks`; const sel=$('builderPlaybookSelect'); sel.innerHTML=''; for(const item of state.builderCatalog){ const opt=document.createElement('option'); opt.value=item.playbook_id; opt.textContent=`${item.name||item.playbook_id} · ${item.category||'general'}`; sel.appendChild(opt); } renderCards('builderCatalog', state.builderCatalog, item=>`<div class="builder-catalog-card"><h4>${item.name||item.playbook_id}</h4><small>${item.playbook_id} · ${item.category||'general'}</small><p>${item.description||''}</p><div class="tag-row">${(item.tags||[]).map(tag=>`<span class="tag">${tag}</span>`).join('')}</div></div>`); [...$('builderCatalog').children].forEach((div,idx)=>div.onclick=()=>{ $('builderPlaybookSelect').value=state.builderCatalog[idx].playbook_id; loadBuilderPlaybook(); }); }
async function refreshBuilderCatalog(){ const data=await api('/workflow-builder/schema'); renderBuilderCatalog(data.starter_playbooks||[]); return data; }
async function loadBuilderPlaybook(){ const playbookId=$('builderPlaybookSelect').value; if(!playbookId)return; const data=await api(`/workflow-builder/playbooks/${encodeURIComponent(playbookId)}`); const playbook=data.playbook||{}; $('builderName').value=playbook.name||playbook.playbook_id||''; $('builderInput').value=pretty(playbook.defaults||{}); $('builderDefinition').value=pretty(playbook.definition||{steps:[]}); renderBuilderValidation({ok:data.ok, warnings:data.builder?.warnings||[], errors:data.builder?.errors||[], stats:data.builder?.stats||{}}); renderBuilderGraph(data.builder?.graph||{nodes:[],edges:[]}); setStatus(`Loaded playbook ${playbook.playbook_id||playbookId}`,'ok'); return data; }
async function validateBuilder(){ try{ const definition=parseJsonInput($('builderDefinition').value,{steps:[]}); const data=await api('/workflow-builder/validate',{method:'POST',body:JSON.stringify({definition})}); renderBuilderValidation(data); renderBuilderGraph(data.graph||{nodes:[],edges:[]}); setStatus(data.ok?'Builder validation passed':'Builder validation found issues', data.ok?'ok':'danger'); return data; }catch(err){ $('builderValidation').textContent=err.message; setStatus(err.message,'danger'); throw err; } }
async function createBuilderWorkflow(){ try{ const definition=parseJsonInput($('builderDefinition').value,{steps:[]}); const input=parseJsonInput($('builderInput').value,{}); const payload={name:$('builderName').value.trim()||'visual workflow',definition,input,autorun:$('builderAutorun').checked,playbook_id:$('builderPlaybookSelect').value||null}; const data=await api('/workflow-builder/create',{method:'POST',body:JSON.stringify(payload)}); renderBuilderGraph(data.builder?.graph||{nodes:[],edges:[]}); $('builderValidation').textContent=pretty(data); setStatus(`Workflow ${data.workflow?.workflow_id||''} created`,'ok'); await refreshAdmin().catch(()=>{}); return data; }catch(err){ $('builderValidation').textContent=err.message; setStatus(err.message,'danger'); throw err; } }
function defaultPolicyExplorerRequest(){ return {scope:'tool',resource_name:'web_fetch',action:'use',agent_name:$('agentSelect')?.value||'researcher',user_role:state.me?.role||'user',tenant_id:state.me?.tenant_id||null,workspace_id:state.me?.workspace_id||null,environment:state.me?.environment||null,channel:null,domain:null,tool_name:null,extra:{}}; }
function parsePolicyExplorerRequest(){ return parseJsonInput($('policyExplorerRequest').value,defaultPolicyExplorerRequest()); }
async function refreshPolicyExplorerSnapshot(){ if(!isAdminLike()) return; const data=await api('/admin/policy-explorer/snapshot'); $('policySnapshotBox').textContent=pretty(data.policy||{}); $('policySignatureBadge').textContent=data.signature?`sig ${String(data.signature).slice(0,12)}`:'No signature'; if(!$('policyExplorerCandidate').value.trim()) $('policyExplorerCandidate').value=yamlLike(data.policy||{}); if(!$('policyExplorerRequest').value.trim()) $('policyExplorerRequest').value=pretty(defaultPolicyExplorerRequest()); $('policyExplorerSummary').textContent=pretty({sections:data.sections,supported_scopes:data.supported_scopes}); return data; }
function renderSecretCatalog(items){ renderCards('secretCatalogBox', items||[], item=>`<strong>${item.ref}</strong><small>${item.description||''}</small><small>usage ${item.usage_count||0} · rotation ${(item.rotation||{}).status||'unknown'}</small><div>${(item.allowed_tools||[]).join(', ')||'all tools'} · ${(item.allowed_roles||[]).join(', ')||'all roles'}</div>`); [...$('secretCatalogBox').children].forEach((div,idx)=>div.onclick=()=>{ const item=(items||[])[idx]||{}; $('secretFilterRef').value=item.ref||''; $('secretFilterTool').value=(item.allowed_tools||[])[0]||$('secretFilterTool').value||''; $('secretExplainRole').value=(item.allowed_roles||[])[0]||$('secretExplainRole').value||'admin'; $('secretSummaryBox').textContent=pretty(item); }); }
function renderSecretUsage(items){ renderCards('secretUsageBox', items||[], item=>`<strong>${item.ref}</strong><small>${item.count||0} resolves</small><small>${(item.tools||[]).join(', ')||''}</small><div>${(item.domains||[]).join(', ')||''}</div>`); [...$('secretUsageBox').children].forEach((div,idx)=>div.onclick=()=>{ const item=(items||[])[idx]||{}; $('secretFilterRef').value=item.ref||''; $('secretFilterTool').value=(item.tools||[])[0]||$('secretFilterTool').value||''; $('secretUsageSummaryBox').textContent=pretty(item); }); }
function secretQueryString(extra={}){ const params=new URLSearchParams(); const filters={ q:($('secretFilterQ').value||'').trim(), ref:($('secretFilterRef').value||'').trim(), tool_name:($('secretFilterTool').value||'').trim(), limit:Math.max(1,Math.min(500,Number($('secretLimit').value||100))), ...extra}; Object.entries(filters).forEach(([k,v])=>{ if(v===undefined || v===null || v==='') return; params.set(k,String(v)); }); return params.toString(); }
async function refreshSecretGovernance(){ if(!isAdminLike()) return; const catalog=await api(`/admin/secrets/catalog?${secretQueryString()}`); const usage=await api(`/admin/secrets/usage?${secretQueryString()}`); renderOverview('secretOverview', [['visible refs', catalog.summary?.visible_refs||0],['configured refs', catalog.summary?.configured_refs||0],['usage events', catalog.summary?.usage_events||0],['enabled', catalog.summary?.enabled?'yes':'no']]); renderOverview('secretUsageOverview', [['usage groups', usage.summary?.usage_groups||0],['raw events', usage.summary?.raw_events||0],['refs observed', usage.summary?.refs_observed||0],['filter ref', usage.filters?.ref||'all']]); $('secretSummaryBox').textContent=pretty({summary:catalog.summary||{},filters:catalog.filters||{}}); $('secretUsageSummaryBox').textContent=pretty({summary:usage.summary||{},filters:usage.filters||{}}); renderSecretCatalog(catalog.items||[]); renderSecretUsage(usage.items||[]); return {catalog,usage}; }
async function explainSecretGovernance(){ const payload={ ref:($('secretFilterRef').value||'').trim(), tool_name:($('secretFilterTool').value||'').trim(), user_role:($('secretExplainRole').value||'admin').trim()||'admin', tenant_id:($('secretExplainTenant').value||'').trim()||null, workspace_id:($('secretExplainWorkspace').value||'').trim()||null, environment:($('secretExplainEnvironment').value||'').trim()||null, domain:($('secretFilterDomain').value||'').trim()||null }; if(!payload.ref || !payload.tool_name) throw new Error('Secret ref and tool name are required'); const data=await api('/admin/secrets/explain',{method:'POST',body:JSON.stringify(payload)}); $('secretExplainBox').textContent=pretty(data); setStatus(data.allowed?`Secret ${payload.ref} allowed for ${payload.tool_name}`:`Secret ${payload.ref} denied for ${payload.tool_name}`, data.allowed?'ok':'danger'); return data; }
async function simulatePolicyExplorer(useCandidate){ if(!isAdminLike()) return; try{ const payload={request:parsePolicyExplorerRequest()}; if(useCandidate){ payload.candidate_policy_yaml=$('policyExplorerCandidate').value; } const data=await api('/admin/policy-explorer/simulate',{method:'POST',body:JSON.stringify(payload)}); $('policySimulationBox').textContent=pretty(data); $('policyExplorerSummary').textContent=pretty(data.change_summary||{changed:data.changed}); setStatus(useCandidate?(data.changed?'Candidate policy changes the decision':'Candidate policy keeps the same decision'):'Current policy simulated', data.changed?'ok':'muted'); return data; }catch(err){ $('policySimulationBox').textContent=err.message; setStatus(err.message,'danger'); throw err; } }
async function diffPolicyExplorer(){ if(!isAdminLike()) return; try{ const payload={candidate_policy_yaml:$('policyExplorerCandidate').value,samples:[parsePolicyExplorerRequest()]}; const data=await api('/admin/policy-explorer/diff',{method:'POST',body:JSON.stringify(payload)}); $('policyDiffBox').textContent=pretty(data); $('policyExplorerSummary').textContent=pretty(data.diff?.summary||{}); setStatus('Policy diff computed','ok'); return data; }catch(err){ $('policyDiffBox').textContent=err.message; setStatus(err.message,'danger'); throw err; } }
function yamlLike(value){ try{ return pretty(value); }catch(_err){ return String(value||''); } }
async function sendChat(){ const message=$('chatInput').value.trim(); if(!message)return; const agent=$('agentSelect').value||'default'; if(!state.currentSessionId) state.currentSessionId=`ui:${Date.now()}`; $('chatSessionLabel').textContent=state.currentSessionId; addChat('user',message); $('chatInput').value=''; if(!$('chatStreamToggle').checked){ const data=await api('/chat',{method:'POST',body:JSON.stringify({message,agent_id:agent,session_id:state.currentSessionId})}); addChat('assistant',data.text||''); await Promise.all([refreshSessions(),refreshHistory(),refreshPending(),refreshToolCalls()]); return; }
  const bubble=addChat('assistant','',true);
  const res=await fetch(`${state.baseUrl}/chat/stream`,{method:'POST',headers:jsonHeaders(),body:JSON.stringify({message,agent_id:agent,session_id:state.currentSessionId})});
  if(!res.ok){ bubble.textContent=await res.text(); bubble.classList.remove('pending'); return; }
  const reader=res.body.getReader(); const decoder=new TextDecoder(); let buffer='';
  while(true){ const {value,done}=await reader.read(); if(done)break; buffer+=decoder.decode(value,{stream:true}); const events=buffer.split('\n\n'); buffer=events.pop()||''; for(const evt of events){ const lines=evt.split('\n'); const eventName=(lines.find(l=>l.startsWith('event: '))||'event: message').slice(7); const dataLine=lines.find(l=>l.startsWith('data: ')); if(!dataLine) continue; const data=JSON.parse(dataLine.slice(6)); if(eventName==='delta'){ bubble.textContent=data.text||((bubble.textContent||'')+(data.delta||'')); } else if(eventName==='status'){ setStatus(`Chat ${data.stage}`); } else if(eventName==='error'){ bubble.textContent=data.detail||'Error'; bubble.classList.remove('pending'); setStatus(data.detail||'Error','danger'); } else if(eventName==='done'){ bubble.textContent=data.text||bubble.textContent; bubble.classList.remove('pending'); setStatus('Chat completed','ok'); } }}
  await Promise.all([refreshSessions(),refreshHistory(),refreshPending(),refreshToolCalls()]);
}
function renderTimeline(boxId, statsId, items){ const box=$(boxId); box.innerHTML=''; for(const item of items||[]){ const div=document.createElement('div'); div.className='card'; const meta=[]; if(item.kind) meta.push(item.kind); if(item.status!==undefined && item.status!==null) meta.push(String(item.status)); if(item.tool_name) meta.push(item.tool_name); if(item.provider||item.model) meta.push(`${item.provider||''} ${item.model||''}`.trim()); div.innerHTML=`<strong>${item.label||item.kind||'item'}</strong><small>${new Date((item.ts||0)*1000).toLocaleString()} · ${meta.join(' · ')}</small><div>${item.content||JSON.stringify(item.payload||item)}</div>`; box.appendChild(div);} if(statsId) $(statsId).textContent=`${(items||[]).length} timeline items`; }
function renderReplayTimeline(items){ renderTimeline('replayTimelineBox','replayTimelineStats',items); }
async function loadSessionReplay(sessionId){ const id=(sessionId||$('replaySessionId').value||state.currentSessionId||'').trim(); if(!id) throw new Error('Session ID required'); $('replaySessionId').value=id; const limit=Math.max(1,Math.min(500,Number($('replayLimit').value||120))); const data=await api(`/admin/replay/sessions/${encodeURIComponent(id)}?limit=${limit}`); $('replaySummaryBox').textContent=pretty(data.summary||{}); $('replayDetailsBox').textContent=pretty({session:data.session,messages:data.messages,tool_calls:data.tool_calls,traces:data.traces}); renderReplayTimeline(data.timeline||[]); $('replayCompareLeftId').value=id; $('replayCompareLeftKind').value='session'; setStatus(`Replay loaded for session ${id}`,'ok'); return data; }
async function loadWorkflowReplay(workflowId){ const id=(workflowId||$('replayWorkflowId').value||'').trim(); if(!id) throw new Error('Workflow ID required'); $('replayWorkflowId').value=id; const limit=Math.max(1,Math.min(500,Number($('replayLimit').value||120))); const data=await api(`/admin/replay/workflows/${encodeURIComponent(id)}?limit=${limit}`); $('replaySummaryBox').textContent=pretty(data.summary||{}); $('replayDetailsBox').textContent=pretty({workflow:data.workflow,approvals:data.approvals,messages:data.messages,tool_calls:data.tool_calls,traces:data.traces}); renderReplayTimeline(data.timeline||[]); $('replayCompareLeftId').value=id; $('replayCompareLeftKind').value='workflow'; setStatus(`Replay loaded for workflow ${id}`,'ok'); return data; }
function renderReplayCompareSummary(data){ const summary=[['changed', data.changed?'yes':'no'],['status changed', data.status?.changed?'yes':'no'],['metric deltas', Object.keys(data.metrics_diff||{}).length],['event diffs', (data.event_name_diff?.changed||[]).length],['tool diffs', (data.tool_diff?.changed||[]).length],['timeline kind diffs', (data.timeline_kind_diff?.changed||[]).length]]; renderOverview('replayCompareSummary', summary); const highlights=[]; for(const item of (data.metrics_diff?Object.entries(data.metrics_diff):[])){ const [name,val]=item; if(Math.abs(Number(val?.delta||0))>0) highlights.push(`<strong>${name}</strong><small>${val.left} → ${val.right}</small><small>Δ ${val.delta}</small>`); } for(const item of (data.timeline_signature_diff?.items||[]).slice(0,6)){ if(Number(item.delta||0)!==0) highlights.push(`<strong>${item.name}</strong><small>${item.left} → ${item.right}</small><small>Δ ${item.delta}</small>`); } $('replayCompareHighlights').innerHTML=highlights.length?highlights.map(html=>`<div class="card">${html}</div>`).join(''):'<div class="card"><small>No standout structural changes</small></div>'; }
async function compareReplay(){ const payload={ left_kind:$('replayCompareLeftKind').value, left_id:$('replayCompareLeftId').value.trim(), right_kind:$('replayCompareRightKind').value, right_id:$('replayCompareRightId').value.trim(), limit:Math.max(1,Math.min(500,Number($('replayLimit').value||120))) }; if(!payload.left_id || !payload.right_id) throw new Error('Both replay IDs are required'); const data=await api('/admin/replay/compare',{method:'POST',body:JSON.stringify(payload)}); renderReplayCompareSummary(data); $('replayCompareBox').textContent=pretty(data); setStatus(data.changed?'Replay comparison shows changes':'Replay comparison shows no structural changes', data.changed?'ok':'muted'); return data; }
function bindClickableCards(boxId, items, idField, cb){ [...$(boxId).children].forEach((div,idx)=>div.onclick=()=>cb(items[idx]?.[idField])); }
function getOperatorFilters(){ return { q:($('operatorFilterQ')?.value||'').trim(), kind:$('operatorFilterKind')?.value||'', status:$('operatorFilterStatus')?.value||'', only_failures:!!$('operatorOnlyFailures')?.checked, limit:Math.max(1,Math.min(500,Number($('operatorLimit')?.value||200))) }; }
function operatorQueryString(extra={}){ const params=new URLSearchParams(); const filters={...getOperatorFilters(),...extra}; Object.entries(filters).forEach(([k,v])=>{ if(v===undefined || v===null || v==='' || v===false) return; params.set(k,String(v)); }); return params.toString(); }
function renderOperatorActionButtons(item, type){ const actions=(item?.available_actions||[]); if(!actions.length) return ''; const buttons=[]; if(type==='workflow' && actions.includes('cancel')) buttons.push(`<button class="ghost action-btn" data-action="cancel" data-type="workflow" data-id="${item.workflow_id}">Cancel</button>`); if(type==='approval'){ if(actions.includes('claim')) buttons.push(`<button class="ghost action-btn" data-action="claim" data-type="approval" data-id="${item.approval_id}">Claim</button>`); if(actions.includes('approve')) buttons.push(`<button class="ghost action-btn" data-action="approve" data-type="approval" data-id="${item.approval_id}">Approve</button>`); if(actions.includes('reject')) buttons.push(`<button class="ghost action-btn" data-action="reject" data-type="approval" data-id="${item.approval_id}">Reject</button>`); }
return buttons.length?`<div class="row wrap">${buttons.join('')}</div>`:''; }
function bindOperatorActionButtons(){ document.querySelectorAll('#operatorTab .action-btn').forEach(btn=>{ btn.onclick=async(ev)=>{ ev.stopPropagation(); const type=btn.dataset.type; const action=btn.dataset.action; const id=btn.dataset.id; try{ if(type==='workflow'){ $('operatorActionWorkflowId').value=id; await runOperatorWorkflowAction(action,id); } else { $('operatorActionApprovalId').value=id; await runOperatorApprovalAction(action,id); } }catch(err){ setStatus(err.message,'danger'); } }; }); }
async function refreshOperatorConsole(){ if(!isAdminLike()) return; const qs=operatorQueryString(); const data=await api(`/admin/operator/overview?${qs}`); renderOverview('operatorOverview', [['sessions', data.summary?.sessions||0],['workflows', data.summary?.workflows||0],['pending approvals', data.summary?.approvals_pending||0],['decision traces', data.summary?.decision_traces||0],['tool failures', data.summary?.tool_failures||0],['workflow failures', data.summary?.workflow_failures||0]]); renderOverview('operatorQueues', [['approvals', data.queues?.approvals_pending||0],['active workflows', data.queues?.workflows_active||0],['active sessions', data.queues?.sessions_active||0],['filtered sessions', data.filtered_counts?.recent_sessions||0],['filtered workflows', data.filtered_counts?.recent_workflows||0],['filtered failures', data.filtered_counts?.recent_failures||0]]); $('operatorPolicySummaryBox').textContent=pretty(data.policy||{}); $('operatorFiltersBox').textContent=pretty({filters:data.filters||{},filtered_counts:data.filtered_counts||{}}); renderCards('operatorRecentFailures', data.recent_failures||[], item=>`<strong>${item.kind}</strong><small>${item.label||item.id}</small><small>${item.status||''}</small><div>${item.error||''}</div>`); renderCards('operatorRecentSessions', data.recent_sessions||[], item=>`<strong>${item.session_id}</strong><small>${item.channel} · ${item.user_id}</small><small>${item.last_message?`${item.last_message.role}: ${item.last_message.content}`:'No messages yet'}</small>`); renderCards('operatorRecentWorkflows', data.recent_workflows||[], item=>`<strong>${item.name||item.workflow_id}</strong><small>${item.workflow_id}</small><small>${item.status||''}</small>${renderOperatorActionButtons(item,'workflow')}`); renderCards('operatorPendingApprovals', data.pending_approvals||[], item=>`<strong>${item.approval_id}</strong><small>${item.workflow_id} · ${item.requested_role}</small><small>${item.status}</small><div>${JSON.stringify(item.payload||{})}</div>${renderOperatorActionButtons(item,'approval')}`); renderCards('operatorRecentTraces', data.recent_traces||[], item=>`<strong>${item.trace_id}</strong><small>${item.agent_id||''} · ${item.status||''}</small><small>${item.provider||''} ${item.model||''}</small>`); bindClickableCards('operatorRecentSessions', data.recent_sessions||[], 'session_id', (id)=>loadOperatorSession(id).catch(err=>setStatus(err.message,'danger'))); bindClickableCards('operatorRecentWorkflows', data.recent_workflows||[], 'workflow_id', (id)=>loadOperatorWorkflow(id).catch(err=>setStatus(err.message,'danger'))); bindOperatorActionButtons(); if(!$('operatorSummaryBox').textContent.trim()) $('operatorSummaryBox').textContent=pretty(data.summary||{}); return data; }
async function loadOperatorSession(sessionId){ if(!isAdminLike()) return; const id=(sessionId||$('operatorSessionId').value||state.currentSessionId||'').trim(); if(!id) throw new Error('Session ID required'); $('operatorSessionId').value=id; state.currentSessionId=id; const qs=operatorQueryString(); const data=await api(`/admin/operator/sessions/${encodeURIComponent(id)}?${qs}`); $('operatorSummaryBox').textContent=pretty(data.summary||{}); $('operatorInspectorBox').textContent=pretty({session:data.session,inspector:data.inspector,messages:data.messages,traces:data.traces,tool_calls:data.tool_calls}); $('operatorPolicyBox').textContent=pretty(data.policy_hints||{}); $('operatorFiltersBox').textContent=pretty({filters:data.filters||{},kind:'session'}); renderTimeline('operatorTimelineBox','operatorTimelineStats',data.timeline||[]); setStatus(`Operator console loaded for session ${id}`,'ok'); return data; }
async function loadOperatorWorkflow(workflowId){ if(!isAdminLike()) return; const id=(workflowId||$('operatorWorkflowId').value||'').trim(); if(!id) throw new Error('Workflow ID required'); $('operatorWorkflowId').value=id; $('operatorActionWorkflowId').value=id; const qs=operatorQueryString(); const data=await api(`/admin/operator/workflows/${encodeURIComponent(id)}?${qs}`); $('operatorSummaryBox').textContent=pretty(data.summary||{}); $('operatorInspectorBox').textContent=pretty({workflow:data.workflow,inspector:data.inspector,approvals:data.approvals,traces:data.traces,tool_calls:data.tool_calls}); $('operatorPolicyBox').textContent=pretty(data.policy_hints||{}); $('operatorFiltersBox').textContent=pretty({filters:data.filters||{},kind:'workflow'}); renderTimeline('operatorTimelineBox','operatorTimelineStats',data.timeline||[]); bindOperatorActionButtons(); setStatus(`Operator console loaded for workflow ${id}`,'ok'); return data; }
async function runOperatorWorkflowAction(action, workflowId){ const id=(workflowId||$('operatorActionWorkflowId').value||$('operatorWorkflowId').value||'').trim(); if(!id) throw new Error('Workflow ID required'); const data=await api(`/admin/operator/workflows/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`,{method:'POST',body:JSON.stringify({reason:$('operatorActionReason').value||''})}); $('operatorActionResultBox').textContent=pretty(data); await refreshOperatorConsole(); await loadOperatorWorkflow(id).catch(()=>{}); setStatus(`Workflow ${action} executed for ${id}`,'ok'); return data; }
async function runOperatorApprovalAction(action, approvalId){ const id=(approvalId||$('operatorActionApprovalId').value||'').trim(); if(!id) throw new Error('Approval ID required'); const data=await api(`/admin/operator/approvals/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`,{method:'POST',body:JSON.stringify({reason:$('operatorActionReason').value||''})}); $('operatorActionResultBox').textContent=pretty(data); if(data.approval?.workflow_id){ $('operatorWorkflowId').value=data.approval.workflow_id; $('operatorActionWorkflowId').value=data.approval.workflow_id; await loadOperatorWorkflow(data.approval.workflow_id).catch(()=>{}); } await refreshOperatorConsole(); setStatus(`Approval ${action} executed for ${id}`,'ok'); return data; }
async function runTerminal(){ $('terminalOutput').textContent=''; const payload={command:$('terminalCommand').value.trim(),cwd:$('terminalCwd').value.trim()||null,confirmed:$('terminalConfirmed').checked,agent_id:$('agentSelect').value||'admin_agent',session_id:state.currentSessionId}; const res=await fetch(`${state.baseUrl}/terminal/stream`,{method:'POST',headers:jsonHeaders(),body:JSON.stringify(payload)}); if(!res.ok){$('terminalOutput').textContent=await res.text(); return;} const reader=res.body.getReader(); const decoder=new TextDecoder(); let buffer=''; while(true){ const {value,done}=await reader.read(); if(done)break; buffer+=decoder.decode(value,{stream:true}); const chunks=buffer.split('\n\n'); buffer=chunks.pop()||''; for(const chunk of chunks){ const line=chunk.split('\n').find(ln=>ln.startsWith('data: ')); if(!line)continue; const data=JSON.parse(line.slice(6)); if(data.type==='stdout') $('terminalOutput').textContent+=data.chunk; else $('terminalOutput').textContent+=`[${data.type}] ${JSON.stringify(data)}\n`; } } await refreshToolCalls(); }

function selectedReleaseId(){ return $('releaseSelectedLabel').dataset.releaseId || ''; }
function parseReleaseItems(){ return parseJsonInput($('releaseItems').value, []); }
async function refreshReleases(){ if(!isAdminLike()) return; const qs=new URLSearchParams(); if($('releaseKind').value.trim()) qs.set('kind',$('releaseKind').value.trim()); if($('releaseEnvironment').value.trim()) qs.set('environment',$('releaseEnvironment').value.trim()); if($('releaseTenant').value.trim()) qs.set('tenant_id',$('releaseTenant').value.trim()); if($('releaseWorkspace').value.trim()) qs.set('workspace_id',$('releaseWorkspace').value.trim()); const data=await api(`/admin/releases${qs.toString()?`?${qs.toString()}`:''}`); $('releaseListSummary').textContent=`${(data.items||[]).length} releases`; renderCards('releaseList', data.items||[], item=>`<strong>${item.name}</strong><small>${item.kind} · ${item.version}</small><small>${item.status} · ${item.environment||'-'}</small><div>${item.release_id}</div>`); [...$('releaseList').children].forEach((div,idx)=>div.onclick=()=>loadReleaseDetail((data.items||[])[idx].release_id)); if(!(data.items||[]).length) $('releaseDetailBox').textContent=''; }
async function loadReleaseDetail(releaseId){ const qs=new URLSearchParams(); if($('releaseTenant').value.trim()) qs.set('tenant_id',$('releaseTenant').value.trim()); if($('releaseWorkspace').value.trim()) qs.set('workspace_id',$('releaseWorkspace').value.trim()); const data=await api(`/admin/releases/${encodeURIComponent(releaseId)}${qs.toString()?`?${qs.toString()}`:''}`); $('releaseSelectedLabel').dataset.releaseId=releaseId; $('releaseSelectedLabel').textContent=releaseId; $('releaseDetailBox').textContent=pretty(data); $('releaseSummaryBox').textContent=pretty(data.release||{}); }
async function createReleaseFromUi(){ const payload={kind:$('releaseKind').value.trim(),name:$('releaseName').value.trim(),version:$('releaseVersion').value.trim(),created_by:$('releaseActor').value.trim()||'admin',environment:$('releaseEnvironment').value.trim()||null,tenant_id:$('releaseTenant').value.trim()||null,workspace_id:$('releaseWorkspace').value.trim()||null,notes:$('releaseReason').value.trim(),items:parseReleaseItems()}; const data=await api('/admin/releases',{method:'POST',body:JSON.stringify(payload)}); $('releaseSelectedLabel').dataset.releaseId=data.release.release_id; $('releaseSelectedLabel').textContent=data.release.release_id; $('releaseSummaryBox').textContent=pretty(data); await refreshReleases(); await loadReleaseDetail(data.release.release_id); }
async function runReleaseAction(action){ const releaseId=selectedReleaseId(); if(!releaseId) throw new Error('Select a release first'); const payload={actor:$('releaseActor').value.trim()||'admin',reason:$('releaseReason').value.trim(),to_environment:$('releaseTargetEnvironment').value.trim()||null,tenant_id:$('releaseTenant').value.trim()||null,workspace_id:$('releaseWorkspace').value.trim()||null}; const data=await api(`/admin/releases/${encodeURIComponent(releaseId)}/${action}`,{method:'POST',body:JSON.stringify(payload)}); $('releaseSummaryBox').textContent=pretty(data); await refreshReleases(); await loadReleaseDetail(releaseId); }

async function refreshAdmin(){ if(!isAdminLike()) return; const [overview,events,ids,users,roles,sessions,toolCalls,metrics]=await Promise.all([api('/admin/overview'),api('/admin/events'),api('/admin/identities'),api('/auth/users'),api('/auth/roles'),api('/admin/sessions'),api('/admin/tool-calls'),api('/metrics/summary')]); renderOverview('adminOverview', [['sessions', overview.summary.sessions],['memory', overview.summary.memory.total],['tool calls', overview.summary.tool_calls],['auth users', overview.auth_users]]); renderOverview('adminChannels', Object.entries(overview.channels).map(([k,v])=>[k,v?'on':'off'])); renderCards('adminEvents', events.items||[], item=>`<strong>${item.channel} · ${item.direction}</strong><small>${new Date(item.ts*1000).toLocaleString()} · ${item.user_id}</small><div>${JSON.stringify(item.payload)}</div>`); renderCards('adminIdentities', ids.items||[], item=>`<strong>${item.channel_user_key}</strong><small>→ ${item.global_user_key}</small><small>${new Date(item.linked_at*1000).toLocaleString()}</small>`); renderCards('adminUsers', users.items||[], item=>`<strong>${item.username}</strong><small>${item.user_key} · ${item.role}</small><small>${(item.permissions||[]).join(', ')}</small>`); renderCards('roleCatalog', roles.items||[], item=>`<strong>${item.role}</strong><small>${(item.permissions||[]).join(', ')}</small>`); renderCards('adminSessions', sessions.items||[], item=>`<strong>${item.session_id}</strong><small>${item.channel} · ${item.user_id}</small><small>${item.last_message?`${item.last_message.role}: ${item.last_message.content}`:'No messages yet'}</small>`); renderCards('adminToolCalls', toolCalls.items||[], item=>`<strong>${item.tool_name}</strong><small>${item.agent_id} · ${item.user_key}</small><small>${item.ok?'ok':'error'} · ${Math.round(item.duration_ms)} ms</small><div>${item.result_excerpt||item.error||''}</div>`); $('adminMetricsBox').textContent=JSON.stringify(metrics,null,2); await refreshAdminMemory(); }
async function refreshAdminMemory(){ if(!isAdminLike()) return; const qs=new URLSearchParams(); if($('adminMemoryQuery').value.trim()) qs.set('q',$('adminMemoryQuery').value.trim()); if($('adminMemoryUserKey').value.trim()) qs.set('user_key',$('adminMemoryUserKey').value.trim()); const data=await api(`/admin/memory/search${qs.toString()?`?${qs.toString()}`:''}`); renderCards('adminMemory', data.items||[], item=>`<strong>${item.kind||'memory'}</strong><small>${item.user_key||''} · ${item.tier||''}</small><div>${item.text||item.content||''}</div>`); }
async function reloadConfig(){ const data=await api('/admin/reload',{method:'POST'}); $('reloadResult').textContent=JSON.stringify(data); }
async function createUser(){ const payload={username:$('newUsername').value.trim(),password:$('newPassword').value,role:$('newRole').value,user_key:$('newUserKey').value.trim()||null}; const data=await api('/auth/users',{method:'POST',body:JSON.stringify(payload)}); $('createUserResult').textContent=`Created ${data.user.username}`; $('newPassword').value=''; await refreshAdmin(); }
function reconnectLive(){ if(state.liveAbort) state.liveAbort.abort(); if(!state.token) return; const controller=new AbortController(); state.liveAbort=controller; const qs = new URLSearchParams(); if(state.currentSessionId) qs.set('session_id', state.currentSessionId); fetch(`${state.baseUrl}/stream/live${qs.toString()?`?${qs.toString()}`:''}`,{headers:authHeader(),signal:controller.signal}).then(async res=>{ if(!res.ok) throw new Error(await res.text()); const reader=res.body.getReader(); const decoder=new TextDecoder(); let buffer=''; while(true){ const {value,done}=await reader.read(); if(done) break; buffer += decoder.decode(value,{stream:true}); const chunks=buffer.split('\n\n'); buffer=chunks.pop()||''; for(const chunk of chunks){ const lines=chunk.split('\n'); const eventName=(lines.find(l=>l.startsWith('event: '))||'event: message').slice(7); const dataLine=lines.find(l=>l.startsWith('data: ')); if(!dataLine) continue; const data=JSON.parse(dataLine.slice(6)); appendLiveEvent(eventName,data); if(eventName.startsWith('confirmation_')) refreshPending(); if(eventName.startsWith('tool_call_') || eventName==='terminal_end' || eventName==='tool_call_result') refreshToolCalls(); if(eventName==='chat_done') { refreshSessions(); if(data.session_id===state.currentSessionId) refreshHistory(); } if(eventName==='connected') setStatus('Realtime connected','ok'); }} }).catch(err=>{ if(err.name!=='AbortError') setStatus(`Realtime: ${err.message}`,'danger'); }); }


function selectedVoiceSessionId(){ return $('voiceSelectedLabel')?.dataset.voiceSessionId||''; }
function renderVoiceSessionList(items){ renderCards('voiceSessionList', items||[], item=>`<strong>${item.voice_session_id}</strong><small>${item.status} · ${item.locale}</small><small>${item.user_key||''}</small><div>${item.last_transcript_text||item.last_output_text||''}</div>`); [...$('voiceSessionList').children].forEach((div,idx)=>div.onclick=()=>loadVoiceSession((items||[])[idx].voice_session_id)); $('voiceListSummary').textContent=`${(items||[]).length} sessions`; }
async function refreshVoiceSessions(){ if(!isAdminLike()) return; const qs=new URLSearchParams(); if($('voiceTenant').value.trim()) qs.set('tenant_id',$('voiceTenant').value.trim()); if($('voiceWorkspace').value.trim()) qs.set('workspace_id',$('voiceWorkspace').value.trim()); const data=await api(`/admin/voice/sessions${qs.toString()?`?${qs.toString()}`:''}`); renderVoiceSessionList(data.items||[]); if(!(data.items||[]).length){ $('voiceTranscriptList').innerHTML=''; $('voiceOutputList').innerHTML=''; } return data; }
async function loadVoiceSession(voiceSessionId){ const qs=new URLSearchParams(); if($('voiceTenant').value.trim()) qs.set('tenant_id',$('voiceTenant').value.trim()); if($('voiceWorkspace').value.trim()) qs.set('workspace_id',$('voiceWorkspace').value.trim()); const data=await api(`/admin/voice/sessions/${encodeURIComponent(voiceSessionId)}${qs.toString()?`?${qs.toString()}`:''}`); $('voiceSelectedLabel').dataset.voiceSessionId=voiceSessionId; $('voiceSelectedLabel').textContent=voiceSessionId; $('voiceSummaryBox').textContent=pretty(data); renderCards('voiceTranscriptList', data.transcripts||[], item=>`<strong>${item.stage}</strong><small>${item.direction} · ${item.language||''}</small><div>${item.text}</div>`); renderCards('voiceOutputList', [...(data.outputs||[]).map(item=>({kind:'output',...item})), ...(data.commands||[]).map(item=>({kind:'command',...item}))], item=>item.kind==='command'?`<strong>${item.command_name}</strong><small>${item.status} · confirm=${item.requires_confirmation}</small><div>${JSON.stringify(item.command_payload||{})}</div>`:`<strong>${item.voice_name}</strong><small>${item.status}</small><div>${item.text}</div>`); return data; }
async function startVoiceSession(){ const payload={user_key:$('voiceUserKey').value.trim()||'voice-user',locale:$('voiceLocale').value.trim()||'es-ES',tenant_id:$('voiceTenant').value.trim()||null,workspace_id:$('voiceWorkspace').value.trim()||null}; const data=await api('/admin/voice/sessions',{method:'POST',body:JSON.stringify(payload)}); $('voiceSelectedLabel').dataset.voiceSessionId=data.session.voice_session_id; $('voiceSelectedLabel').textContent=data.session.voice_session_id; $('voiceSummaryBox').textContent=pretty(data); await refreshVoiceSessions(); await loadVoiceSession(data.session.voice_session_id); }
async function transcribeVoiceTurn(){ const voiceSessionId=selectedVoiceSessionId(); if(!voiceSessionId) throw new Error('Start or select a voice session first'); const payload={transcript_text:$('voiceTranscriptText').value.trim(),tenant_id:$('voiceTenant').value.trim()||null,workspace_id:$('voiceWorkspace').value.trim()||null}; const data=await api(`/admin/voice/sessions/${encodeURIComponent(voiceSessionId)}/transcribe`,{method:'POST',body:JSON.stringify(payload)}); $('voiceSummaryBox').textContent=pretty(data); await refreshVoiceSessions(); await loadVoiceSession(voiceSessionId); }
async function respondVoiceTurn(){ const voiceSessionId=selectedVoiceSessionId(); if(!voiceSessionId) throw new Error('Start or select a voice session first'); const payload={text:$('voiceTranscriptText').value.trim(),voice_name:$('voiceName').value.trim()||'assistant',tenant_id:$('voiceTenant').value.trim()||null,workspace_id:$('voiceWorkspace').value.trim()||null}; const data=await api(`/admin/voice/sessions/${encodeURIComponent(voiceSessionId)}/respond`,{method:'POST',body:JSON.stringify(payload)}); $('voiceSummaryBox').textContent=pretty(data); await loadVoiceSession(voiceSessionId); }
async function confirmVoiceTurn(decision='confirm'){ const voiceSessionId=selectedVoiceSessionId(); if(!voiceSessionId) throw new Error('Start or select a voice session first'); const payload={decision,confirmation_text:$('voiceTranscriptText').value.trim(),tenant_id:$('voiceTenant').value.trim()||null,workspace_id:$('voiceWorkspace').value.trim()||null}; const data=await api(`/admin/voice/sessions/${encodeURIComponent(voiceSessionId)}/confirm`,{method:'POST',body:JSON.stringify(payload)}); $('voiceSummaryBox').textContent=pretty(data); await refreshVoiceSessions(); await loadVoiceSession(voiceSessionId); }
async function closeVoiceSession(){ const voiceSessionId=selectedVoiceSessionId(); if(!voiceSessionId) throw new Error('Start or select a voice session first'); const payload={reason:'closed from ui',tenant_id:$('voiceTenant').value.trim()||null,workspace_id:$('voiceWorkspace').value.trim()||null}; const data=await api(`/admin/voice/sessions/${encodeURIComponent(voiceSessionId)}/close`,{method:'POST',body:JSON.stringify(payload)}); $('voiceSummaryBox').textContent=pretty(data); await refreshVoiceSessions(); await loadVoiceSession(voiceSessionId); }

function renderAppInstallationList(items){ renderCards('appInstallationList', items, item=>`<strong>${item.device_label||item.platform}</strong><small>${item.installation_id}</small><small>${item.user_key} · ${item.notification_permission} · ${item.push_capable?'push':'no push'}</small>`); [...$('appInstallationList').children].forEach((div,idx)=>div.onclick=()=>{ $('appNotificationInstallationId').value=items[idx].installation_id; $('appInstallResultBox').textContent=pretty(items[idx]); }); }
function renderAppNotificationList(items){ renderCards('appNotificationList', items, item=>`<strong>${item.title}</strong><small>${item.category} · ${new Date(item.created_at*1000).toLocaleString()}</small><small>${item.target_path}</small><div>${item.body}</div>`); }
function renderAppDeepLinkList(items){ renderCards('appDeepLinkList', items, item=>`<strong>${item.view} → ${item.target_type}</strong><small>${item.target_id}</small><small>${item.status} · ${(item.expires_at?new Date(item.expires_at*1000).toLocaleString():'no expiry')}</small><div>/app/deep-links/${item.link_token}</div>`); [...$('appDeepLinkList').children].forEach((div,idx)=>div.onclick=()=>{ $('appDeepLinkPreview').textContent=`${location.origin}/app/deep-links/${items[idx].link_token}`; $('appDeepLinkResultBox').textContent=pretty(items[idx]); }); }


function selectedCanvasId(){ return state.currentCanvasId || $('canvasSelectedLabel').dataset.canvasId || ''; }
async function refreshCanvasCore(){ if(!isAdminLike()) return; const qs=new URLSearchParams(); if($('canvasTenant').value.trim()) qs.set('tenant_id',$('canvasTenant').value.trim()); if($('canvasWorkspace').value.trim()) qs.set('workspace_id',$('canvasWorkspace').value.trim()); if($('canvasEnvironment').value.trim()) qs.set('environment',$('canvasEnvironment').value.trim()); const data=await api(`/admin/canvas/documents${qs.toString()?`?${qs.toString()}`:''}`); $('canvasListSummary').textContent=`${(data.items||[]).length} canvas(es)`; renderOverview('canvasOverview', [['Canvases',(data.items||[]).length],['Selected',selectedCanvasId()||'-'],['Env',$('canvasEnvironment').value.trim()||'-']]); renderCards('canvasDocumentList', data.items||[], item=>`<strong>${item.title}</strong><small>${item.status} · ${item.environment||'-'}</small><div>${item.canvas_id}</div>`); [...$('canvasDocumentList').children].forEach((div,idx)=>div.onclick=()=>loadCanvasDetail((data.items||[])[idx].canvas_id)); if(!(data.items||[]).length){ $('canvasDetailBox').textContent=''; $('canvasEventList').innerHTML=''; } return data; }
async function loadCanvasDetail(canvasId){ const qs=new URLSearchParams(); if($('canvasTenant').value.trim()) qs.set('tenant_id',$('canvasTenant').value.trim()); if($('canvasWorkspace').value.trim()) qs.set('workspace_id',$('canvasWorkspace').value.trim()); if($('canvasEnvironment').value.trim()) qs.set('environment',$('canvasEnvironment').value.trim()); const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}${qs.toString()?`?${qs.toString()}`:''}`); state.currentCanvasId=canvasId; $('canvasSelectedLabel').dataset.canvasId=canvasId; $('canvasSelectedLabel').textContent=canvasId; $('canvasDetailBox').textContent=pretty({document:data.document,nodes:data.nodes,edges:data.edges,views:data.views,presence:data.presence,comments:data.comments,snapshots:data.snapshots,presence_events:data.presence_events,overlay_states:data.overlay_states}); renderCards('canvasEventList', data.events||[], item=>`<strong>${item.payload?.action||item.channel}</strong><small>${new Date(item.ts*1000).toLocaleString()}</small><div>${JSON.stringify(item.payload||{})}</div>`); if(document.getElementById('canvasCommentList')) renderCards('canvasCommentList', data.comments||[], item=>`<strong>${item.author||'operator'}</strong><small>${new Date((item.updated_at||item.created_at||0)*1000).toLocaleString()}</small><div>${item.body||''}</div>`); if(document.getElementById('canvasSnapshotList')) renderCards('canvasSnapshotList', data.snapshots||[], item=>`<strong>${item.label||item.snapshot_kind||'snapshot'}</strong><small>${item.snapshot_kind||'manual'} · ${(item.share_token||'').slice(0,8)}</small><div>${JSON.stringify(item.snapshot?.summary||{})}</div>`); if(document.getElementById('canvasPresenceEventList')) renderCards('canvasPresenceEventList', data.presence_events||[], item=>`<strong>${item.user_key||'operator'}</strong><small>${item.event_type||'presence'} · ${new Date((item.created_at||0)*1000).toLocaleString()}</small><div>${JSON.stringify(item.payload||{})}</div>`); if(document.getElementById('canvasCollabSummaryBox')) $('canvasCollabSummaryBox').textContent=pretty({comments:(data.comments||[]).length,snapshots:(data.snapshots||[]).length,presence_events:(data.presence_events||[]).length}); if((data.nodes||[])[0]){ $('canvasEdgeSource').value=(data.nodes||[])[0].node_id; $('canvasPresenceSelectedNode').value=(data.nodes||[])[0].node_id; if(!$('canvasOverlaySelectedNode').value) $('canvasOverlaySelectedNode').value=(data.nodes||[])[0].node_id; } if((data.nodes||[])[1]) $('canvasEdgeTarget').value=(data.nodes||[])[1].node_id; $('canvasEventSummaryBox').textContent=pretty({nodes:(data.nodes||[]).length,edges:(data.edges||[]).length,views:(data.views||[]).length,presence:(data.presence||[]).length,overlay_states:(data.overlay_states||[]).length}); await refreshCanvasOverlays().catch(()=>{}); return data; }
async function createCanvasDocument(){ const payload={actor:'admin',title:$('canvasTitle').value.trim(),description:$('canvasDescription').value.trim(),tenant_id:$('canvasTenant').value.trim()||null,workspace_id:$('canvasWorkspace').value.trim()||null,environment:$('canvasEnvironment').value.trim()||null}; const data=await api('/admin/canvas/documents',{method:'POST',body:JSON.stringify(payload)}); $('canvasCreateResultBox').textContent=pretty(data); state.currentCanvasId=data.document.canvas_id; await refreshCanvasCore(); await loadCanvasDetail(data.document.canvas_id); }
async function upsertCanvasNode(){ const canvasId=selectedCanvasId(); if(!canvasId) throw new Error('Select a canvas first'); const payload={actor:'admin',node_id:$('canvasNodeId').value.trim()||null,node_type:$('canvasNodeType').value.trim()||'note',label:$('canvasNodeLabel').value.trim(),position_x:Number($('canvasNodePosX').value||0),position_y:Number($('canvasNodePosY').value||0),data:{kind:$('canvasNodeType').value.trim()||'note'},tenant_id:$('canvasTenant').value.trim()||null,workspace_id:$('canvasWorkspace').value.trim()||null,environment:$('canvasEnvironment').value.trim()||null}; const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}/nodes`,{method:'POST',body:JSON.stringify(payload)}); $('canvasMutationResultBox').textContent=pretty(data); $('canvasNodeId').value=data.node.node_id; if(!$('canvasEdgeSource').value) $('canvasEdgeSource').value=data.node.node_id; else if(!$('canvasEdgeTarget').value) $('canvasEdgeTarget').value=data.node.node_id; await loadCanvasDetail(canvasId); }
async function upsertCanvasEdge(){ const canvasId=selectedCanvasId(); if(!canvasId) throw new Error('Select a canvas first'); const payload={actor:'admin',source_node_id:$('canvasEdgeSource').value.trim(),target_node_id:$('canvasEdgeTarget').value.trim(),label:$('canvasEdgeLabel').value.trim(),tenant_id:$('canvasTenant').value.trim()||null,workspace_id:$('canvasWorkspace').value.trim()||null,environment:$('canvasEnvironment').value.trim()||null}; const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}/edges`,{method:'POST',body:JSON.stringify(payload)}); $('canvasMutationResultBox').textContent=pretty(data); await loadCanvasDetail(canvasId); }
async function saveCanvasView(){ const canvasId=selectedCanvasId(); if(!canvasId) throw new Error('Select a canvas first'); const payload={actor:'admin',name:$('canvasViewName').value.trim()||'Default',layout:{zoom:1,center:[0,0]},filters:{environment:$('canvasEnvironment').value.trim()||null},is_default:$('canvasViewDefault').checked,tenant_id:$('canvasTenant').value.trim()||null,workspace_id:$('canvasWorkspace').value.trim()||null,environment:$('canvasEnvironment').value.trim()||null}; const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}/views`,{method:'POST',body:JSON.stringify(payload)}); $('canvasViewResultBox').textContent=pretty(data); await loadCanvasDetail(canvasId); }
async function updateCanvasPresence(){ const canvasId=selectedCanvasId(); if(!canvasId) throw new Error('Select a canvas first'); const payload={actor:'admin',user_key:$('canvasPresenceUser').value.trim()||state.username||'operator',cursor_x:Number($('canvasPresenceX').value||0),cursor_y:Number($('canvasPresenceY').value||0),selected_node_id:$('canvasPresenceSelectedNode').value.trim()||null,tenant_id:$('canvasTenant').value.trim()||null,workspace_id:$('canvasWorkspace').value.trim()||null,environment:$('canvasEnvironment').value.trim()||null}; const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}/presence`,{method:'POST',body:JSON.stringify(payload)}); $('canvasViewResultBox').textContent=pretty(data); await loadCanvasDetail(canvasId); }
function canvasOverlayToggles(){ return {policy:$('canvasOverlayPolicy').checked,cost:$('canvasOverlayCost').checked,traces:$('canvasOverlayTraces').checked,failures:$('canvasOverlayFailures').checked,approvals:$('canvasOverlayApprovals').checked,secrets:$('canvasOverlaySecrets').checked}; }
async function refreshCanvasOverlays(){ const canvasId=selectedCanvasId(); if(!canvasId) throw new Error('Select a canvas first'); const qs=new URLSearchParams(); if($('canvasTenant').value.trim()) qs.set('tenant_id',$('canvasTenant').value.trim()); if($('canvasWorkspace').value.trim()) qs.set('workspace_id',$('canvasWorkspace').value.trim()); if($('canvasEnvironment').value.trim()) qs.set('environment',$('canvasEnvironment').value.trim()); if($('canvasOverlaySelectedNode').value.trim()) qs.set('selected_node_id',$('canvasOverlaySelectedNode').value.trim()); qs.set('state_key',$('canvasOverlayStateKey').value.trim()||'default'); const toggles=canvasOverlayToggles(); Object.entries(toggles).forEach(([key,val])=>qs.set(`overlay_${key}`,val?'true':'false')); const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}/overlays?${qs.toString()}`); $('canvasOverlaySummaryBox').textContent=pretty({toggles:data.toggles,inspector:data.inspector,overlay_summaries:Object.fromEntries(Object.entries(data.overlays||{}).map(([k,v])=>[k,v.summary||{}]))}); $('canvasOverlayStateBox').textContent=pretty({state_key:data.state_key,states:data.states||[]}); const cards=[]; Object.entries(data.overlays||{}).forEach(([name,overlay])=>{ if(!(overlay&&overlay.enabled)) return; cards.push({name,summary:overlay.summary||{},items:(overlay.items||[]).slice(0,3),budgets:(overlay.budgets||[]).slice(0,2),catalog:(overlay.catalog||[]).slice(0,2)}); }); renderCards('canvasOverlayList', cards, item=>`<strong>${item.name}</strong><small>${JSON.stringify(item.summary||{})}</small><div>${JSON.stringify({items:item.items,budgets:item.budgets,catalog:item.catalog})}</div>`); return data; }
async function saveCanvasOverlayState(){ const canvasId=selectedCanvasId(); if(!canvasId) throw new Error('Select a canvas first'); const payload={actor:'admin',state_key:$('canvasOverlayStateKey').value.trim()||'default',toggles:canvasOverlayToggles(),inspector:{selected_node_id:$('canvasOverlaySelectedNode').value.trim()||null},tenant_id:$('canvasTenant').value.trim()||null,workspace_id:$('canvasWorkspace').value.trim()||null,environment:$('canvasEnvironment').value.trim()||null}; const data=await api(`/admin/canvas/documents/${encodeURIComponent(canvasId)}/overlay-state`,{method:'POST',body:JSON.stringify(payload)}); $('canvasOverlayStateBox').textContent=pretty(data); await refreshCanvasOverlays(); }

async function refreshAppFoundation(){ if(!isAdminLike()) return; const qs=new URLSearchParams(); if($('appTenant').value.trim()) qs.set('tenant_id',$('appTenant').value.trim()); if($('appWorkspace').value.trim()) qs.set('workspace_id',$('appWorkspace').value.trim()); const suffix=qs.toString()?`?${qs.toString()}`:''; const [installations,notifications,links]=await Promise.all([api(`/admin/app/installations${suffix}`),api(`/admin/app/notifications${suffix}`),api(`/admin/app/deep-links${suffix}`)]); renderAppInstallationList(installations.items||[]); renderAppNotificationList(notifications.items||[]); renderAppDeepLinkList(links.items||[]); $('appInstallationSummary').textContent=`${(installations.items||[]).length} installation(s)`; renderOverview('appOverview',[['Installations',(installations.items||[]).length],['Notifications',(notifications.items||[]).length],['Deep links',(links.items||[]).length],['SW',state.serviceWorkerReady?'ready':'pending']]); await refreshPhase8Packaging().catch(()=>{}); return {installations,notifications,links}; }
async function refreshPhase8Packaging(){ if(!isAdminLike() || !document.getElementById('packagingSummaryBox')) return; const qs=new URLSearchParams(); if($('appTenant').value.trim()) qs.set('tenant_id',$('appTenant').value.trim()); if($('appWorkspace').value.trim()) qs.set('workspace_id',$('appWorkspace').value.trim()); const suffix=qs.toString()?`?${qs.toString()}`:''; const [summary,builds]=await Promise.all([api('/admin/phase8/packaging/summary'),api(`/admin/phase8/packaging/builds${suffix}`)]); $('packagingSummaryBox').textContent=pretty(summary.packaging||{}); $('hardeningSummaryBox').textContent=pretty(summary.hardening||{}); $('packageBuildSummary').textContent=`${(builds.items||[]).length} build(s)`; renderCards('packageBuildList', builds.items||[], item=>`<strong>${item.label}</strong><small>${item.target} · ${item.version} · ${item.status}</small><div>${item.artifact_path||''}</div>`); return {summary,builds}; }
async function recordPackageBuild(){ const payload={target:$('packageBuildTarget').value.trim()||'desktop',label:$('packageBuildLabel').value.trim()||'Phase 8 shell',version:$('packageBuildVersion').value.trim()||'phase8-pr8',artifact_path:$('packageBuildArtifactPath').value.trim()||'',tenant_id:$('appTenant').value.trim()||null,workspace_id:$('appWorkspace').value.trim()||null,environment:null,metadata:{source:'ui',service_worker_ready:state.serviceWorkerReady}}; const data=await api('/admin/phase8/packaging/builds',{method:'POST',body:JSON.stringify(payload)}); $('packageBuildResultBox').textContent=pretty(data); await refreshPhase8Packaging(); }
async function registerCurrentPwa(){ const payload={user_key:$('appUserKey').value.trim()||state.username||'operator',platform:$('appPlatform').value.trim()||'pwa',device_label:$('appDeviceLabel').value.trim()||navigator.userAgent.slice(0,80),push_capable:$('appPushCapable').checked||('serviceWorker' in navigator),notification_permission:$('appNotificationPermission').value.trim()||Notification?.permission||'default',deep_link_base:'/ui/',metadata:{user_agent:navigator.userAgent,viewport:`${window.innerWidth}x${window.innerHeight}`},tenant_id:$('appTenant').value.trim()||null,workspace_id:$('appWorkspace').value.trim()||null}; const data=await api('/admin/app/installations',{method:'POST',body:JSON.stringify(payload)}); $('appInstallResultBox').textContent=pretty(data); if(data.installation?.installation_id) $('appNotificationInstallationId').value=data.installation.installation_id; await refreshAppFoundation(); }
async function createAppNotification(){ const payload={title:$('appNotificationTitle').value.trim(),body:$('appNotificationBody').value.trim(),category:$('appNotificationCategory').value.trim()||'operator',installation_id:$('appNotificationInstallationId').value.trim()||null,target_path:$('appNotificationTargetPath').value.trim()||'/ui/?tab=operator',require_interaction:true,tenant_id:$('appTenant').value.trim()||null,workspace_id:$('appWorkspace').value.trim()||null}; const data=await api('/admin/app/notifications',{method:'POST',body:JSON.stringify(payload)}); $('appNotificationResultBox').textContent=pretty(data); if(state.serviceWorkerReady && 'serviceWorker' in navigator && Notification?.permission==='granted'){ const reg=await navigator.serviceWorker.ready; await reg.showNotification(data.notification.title,{body:data.notification.body,data:{path:data.notification.target_path},tag:data.notification.notification_id}); } await refreshAppFoundation(); }
async function createAppDeepLink(){ const payload={view:$('appDeepLinkView').value.trim()||'operator',target_type:$('appDeepLinkTargetType').value.trim()||'record',target_id:$('appDeepLinkTargetId').value.trim(),params:parseJsonInput($('appDeepLinkParams').value,{tab:'operator'}),expires_in_s:Number($('appDeepLinkExpiry').value||3600),tenant_id:$('appTenant').value.trim()||null,workspace_id:$('appWorkspace').value.trim()||null}; const data=await api('/admin/app/deep-links',{method:'POST',body:JSON.stringify(payload)}); $('appDeepLinkResultBox').textContent=pretty(data); $('appDeepLinkPreview').textContent=`${location.origin}${data.deep_link.url}`; await refreshAppFoundation(); }
async function requestNotificationPermission(){ if(!('Notification' in window)) throw new Error('Notifications are not supported in this browser'); const result=await Notification.requestPermission(); $('appNotificationPermission').value=result; $('pwaSupportBadge').textContent=`Notifications: ${result}`; }
async function installPwa(){ if(state.deferredInstallPrompt){ state.deferredInstallPrompt.prompt(); await state.deferredInstallPrompt.userChoice; state.deferredInstallPrompt=null; $('pwaSupportBadge').textContent='Install prompt used'; return; } $('pwaSupportBadge').textContent='Use your browser install menu to pin openMiura as an app'; }
async function bootstrapPwa(){ const supported=('serviceWorker' in navigator); $('pwaSupportBadge').textContent=supported?'PWA runtime available':'PWA runtime limited in this browser'; $('appPushCapable').checked=supported; $('appNotificationPermission').value=(window.Notification&&Notification.permission)||'default'; if(supported){ try{ await navigator.serviceWorker.register('./service-worker.js'); state.serviceWorkerReady=true; }catch(err){ state.serviceWorkerReady=false; } } window.addEventListener('beforeinstallprompt',evt=>{ evt.preventDefault(); state.deferredInstallPrompt=evt; $('pwaSupportBadge').textContent='Install prompt ready'; }); const params=new URLSearchParams(location.search); const targetTab=params.get('tab'); if(targetTab && document.getElementById(`${targetTab}Tab`)) switchTab(targetTab); if(params.get('target_id')) $('appDeepLinkPreview').textContent=location.href; }

$('baseUrl').value=state.baseUrl; $('token').value=state.token; $('username').value=state.username; $('authModeSelect').value=state.authMode; bindAuthMode();
$('authModeSelect').onchange=()=>{ state.authMode=$('authModeSelect').value; bindAuthMode(); };
$('connectBtn').onclick=connect; $('logoutBtn').onclick=logout; $('refreshAgentsBtn').onclick=refreshAgents; $('refreshSessionsBtn').onclick=refreshSessions; $('refreshHistoryBtn').onclick=refreshHistory; $('refreshPendingBtn').onclick=refreshPending; $('refreshMetricsBtn').onclick=refreshMetrics; $('memorySearchBtn').onclick=memorySearch; $('sendBtn').onclick=sendChat; $('newSessionBtn').onclick=()=>{ state.currentSessionId=`ui:${Date.now()}`; $('chatSessionLabel').textContent=state.currentSessionId; clearChat(); $('historyBox').innerHTML=''; reconnectLive(); }; $('runTerminalBtn').onclick=runTerminal; $('refreshToolCallsBtn').onclick=refreshToolCalls; $('reconnectLiveBtn').onclick=reconnectLive;
$(`refreshBuilderCatalogBtn`).onclick=refreshBuilderCatalog; $('refreshVoiceBtn').onclick=()=>refreshVoiceSessions().catch(err=>setStatus(err.message,'danger')); $('refreshAppFoundationBtn').onclick=()=>refreshAppFoundation().catch(err=>setStatus(err.message,'danger')); $('registerCurrentPwaBtn').onclick=()=>registerCurrentPwa().catch(err=>setStatus(err.message,'danger')); $('createAppNotificationBtn').onclick=()=>createAppNotification().catch(err=>setStatus(err.message,'danger')); $('createAppDeepLinkBtn').onclick=()=>createAppDeepLink().catch(err=>setStatus(err.message,'danger')); $('requestNotificationsBtn').onclick=()=>requestNotificationPermission().catch(err=>setStatus(err.message,'danger')); $('installPwaBtn').onclick=()=>installPwa().catch(err=>setStatus(err.message,'danger'));  $('startVoiceBtn').onclick=()=>startVoiceSession().catch(err=>setStatus(err.message,'danger')); $('transcribeVoiceBtn').onclick=()=>transcribeVoiceTurn().catch(err=>setStatus(err.message,'danger')); $('respondVoiceBtn').onclick=()=>respondVoiceTurn().catch(err=>setStatus(err.message,'danger')); $('confirmVoiceBtn').onclick=()=>confirmVoiceTurn('confirm').catch(err=>setStatus(err.message,'danger')); $('cancelVoiceBtn').onclick=()=>confirmVoiceTurn('cancel').catch(err=>setStatus(err.message,'danger')); $('closeVoiceBtn').onclick=()=>closeVoiceSession().catch(err=>setStatus(err.message,'danger')); $('refreshReleasesBtn').onclick=()=>refreshReleases().catch(err=>setStatus(err.message,'danger')); $('createReleaseBtn').onclick=()=>createReleaseFromUi().catch(err=>setStatus(err.message,'danger')); $('submitReleaseBtn').onclick=()=>runReleaseAction('submit').catch(err=>setStatus(err.message,'danger')); $('approveReleaseBtn').onclick=()=>runReleaseAction('approve').catch(err=>setStatus(err.message,'danger')); $('promoteReleaseBtn').onclick=()=>runReleaseAction('promote').catch(err=>setStatus(err.message,'danger')); $('rollbackReleaseBtn').onclick=()=>runReleaseAction('rollback').catch(err=>setStatus(err.message,'danger')); $('refreshSecretsBtn').onclick=()=>refreshSecretGovernance().catch(err=>setStatus(err.message,'danger')); $('runSecretExplainBtn').onclick=()=>explainSecretGovernance().catch(err=>setStatus(err.message,'danger')); $('copySecretCatalogBtn').onclick=async()=>{ try{ await navigator.clipboard.writeText($('secretSummaryBox').textContent||''); setStatus('Secret catalog copied','ok'); }catch(err){ setStatus(err.message,'danger'); } };  $('refreshOperatorBtn').onclick=()=>refreshOperatorConsole().catch(err=>setStatus(err.message,'danger')); $('applyOperatorFiltersBtn').onclick=()=>refreshOperatorConsole().catch(err=>setStatus(err.message,'danger')); $('loadOperatorSessionBtn').onclick=()=>loadOperatorSession().catch(err=>setStatus(err.message,'danger')); $('loadOperatorWorkflowBtn').onclick=()=>loadOperatorWorkflow().catch(err=>setStatus(err.message,'danger')); $('operatorCancelWorkflowBtn').onclick=()=>runOperatorWorkflowAction('cancel').catch(err=>setStatus(err.message,'danger')); $('operatorClaimApprovalBtn').onclick=()=>runOperatorApprovalAction('claim').catch(err=>setStatus(err.message,'danger')); $('operatorApproveApprovalBtn').onclick=()=>runOperatorApprovalAction('approve').catch(err=>setStatus(err.message,'danger')); $('operatorRejectApprovalBtn').onclick=()=>runOperatorApprovalAction('reject').catch(err=>setStatus(err.message,'danger')); $('loadReplaySessionBtn').onclick=()=>loadSessionReplay().catch(err=>setStatus(err.message,'danger')); $('loadReplayWorkflowBtn').onclick=()=>loadWorkflowReplay().catch(err=>setStatus(err.message,'danger')); $('runReplayCompareBtn').onclick=()=>compareReplay().catch(err=>setStatus(err.message,'danger')); $('copyReplaySummaryBtn').onclick=async()=>{ try{ await navigator.clipboard.writeText($('replaySummaryBox').textContent||''); setStatus('Replay summary copied','ok'); }catch(err){ setStatus(err.message,'danger'); } };  $('loadBuilderPlaybookBtn').onclick=loadBuilderPlaybook; $('validateBuilderBtn').onclick=validateBuilder; $('createBuilderWorkflowBtn').onclick=createBuilderWorkflow; $('formatBuilderDefinitionBtn').onclick=()=>{ try{$('builderDefinition').value=pretty(parseJsonInput($('builderDefinition').value,{steps:[]}));}catch(err){setStatus(err.message,'danger');} }; $('formatBuilderInputBtn').onclick=()=>{ try{$('builderInput').value=pretty(parseJsonInput($('builderInput').value,{}));}catch(err){setStatus(err.message,'danger');} }; $('copyBuilderDefinitionBtn').onclick=async()=>{ try{ await navigator.clipboard.writeText($('builderDefinition').value); setStatus('Definition copied','ok'); }catch(err){ setStatus(err.message,'danger'); } }; $('refreshPolicyExplorerBtn').onclick=refreshPolicyExplorerSnapshot; $('simulateCurrentPolicyBtn').onclick=()=>simulatePolicyExplorer(false); $('simulateCandidatePolicyBtn').onclick=()=>simulatePolicyExplorer(true); $('diffPolicyBtn').onclick=diffPolicyExplorer; $('formatPolicyRequestBtn').onclick=()=>{ try{$('policyExplorerRequest').value=pretty(parsePolicyExplorerRequest());}catch(err){setStatus(err.message,'danger');} }; $('clearPolicyCandidateBtn').onclick=()=>{ $('policyExplorerCandidate').value=''; $('policyDiffBox').textContent=''; $('policySimulationBox').textContent=''; }; $('copyPolicySnapshotBtn').onclick=async()=>{ try{ await navigator.clipboard.writeText($('policySnapshotBox').textContent||''); setStatus('Current policy copied','ok'); }catch(err){ setStatus(err.message,'danger'); } };
$('refreshCanvasBtn').onclick=()=>refreshCanvasCore().catch(err=>setStatus(err.message,'danger')); $('refreshConfigCenterBtn').onclick=()=>refreshConfigCenter().catch(err=>setStatus(err.message,'danger')); $('refreshReloadAssistantBtn').onclick=()=>refreshReloadAssistant().catch(err=>setStatus(err.message,'danger')); $('applyReloadAssistantBtn').onclick=()=>applyReloadAssistant().catch(err=>setStatus(err.message,'danger')); $('configSectionSelect').onchange=()=>selectConfigSection($('configSectionSelect').value); $('validateConfigBtn').onclick=()=>validateConfigCenter().catch(err=>setStatus(err.message,'danger')); $('saveConfigBtn').onclick=()=>saveConfigCenter(false).catch(err=>setStatus(err.message,'danger')); $('saveReloadConfigBtn').onclick=()=>saveConfigCenter(true).catch(err=>setStatus(err.message,'danger')); $('loadConfigFormFromEditorBtn').onclick=()=>loadConfigFormFromEditor().catch(err=>setStatus(err.message,'danger')); $('applyConfigFormBtn').onclick=()=>applyConfigFormToEditor().catch(err=>setStatus(err.message,'danger')); $('saveConfigFormBtn').onclick=()=>saveConfigFormCenter(false).catch(err=>setStatus(err.message,'danger')); $('saveReloadConfigFormBtn').onclick=()=>saveConfigFormCenter(true).catch(err=>setStatus(err.message,'danger')); $('refreshChannelWizardBtn').onclick=()=>refreshChannelWizard().catch(err=>setStatus(err.message,'danger')); $('channelWizardChannelSelect').onchange=()=>selectChannelWizardChannel($('channelWizardChannelSelect').value); $('loadChannelWizardFromEditorBtn').onclick=()=>loadChannelWizardFromEditor().catch(err=>setStatus(err.message,'danger')); $('applyChannelWizardBtn').onclick=()=>applyChannelWizardToEditor().catch(err=>setStatus(err.message,'danger')); $('saveChannelWizardBtn').onclick=()=>saveChannelWizard(false).catch(err=>setStatus(err.message,'danger')); $('saveReloadChannelWizardBtn').onclick=()=>saveChannelWizard(true).catch(err=>setStatus(err.message,'danger')); $('refreshSecretEnvWizardBtn').onclick=()=>refreshSecretEnvWizard().catch(err=>setStatus(err.message,'danger')); $('secretEnvProfileSelect').onchange=()=>selectSecretEnvProfile($('secretEnvProfileSelect').value); $('applySuggestedSecretEnvRefsBtn').onclick=()=>applySuggestedSecretEnvRefs(); $('loadSecretEnvWizardFromEditorBtn').onclick=()=>loadSecretEnvWizardFromEditor().catch(err=>setStatus(err.message,'danger')); $('applySecretEnvWizardBtn').onclick=()=>applySecretEnvWizardToEditor().catch(err=>setStatus(err.message,'danger')); $('saveSecretEnvWizardBtn').onclick=()=>saveSecretEnvWizard(false).catch(err=>setStatus(err.message,'danger')); $('saveReloadSecretEnvWizardBtn').onclick=()=>saveSecretEnvWizard(true).catch(err=>setStatus(err.message,'danger')); $('copyConfigPathBtn').onclick=async()=>{ try{ await navigator.clipboard.writeText($('configFilePath').value||''); setStatus('Config path copied','ok'); }catch(err){ setStatus(err.message,'danger'); } }; $('copyConfigYamlBtn').onclick=async()=>{ try{ await navigator.clipboard.writeText($('configEditor').value||''); setStatus('Config YAML copied','ok'); }catch(err){ setStatus(err.message,'danger'); } }; $('createCanvasBtn').onclick=()=>createCanvasDocument().catch(err=>setStatus(err.message,'danger')); $('upsertCanvasNodeBtn').onclick=()=>upsertCanvasNode().catch(err=>setStatus(err.message,'danger')); $('upsertCanvasEdgeBtn').onclick=()=>upsertCanvasEdge().catch(err=>setStatus(err.message,'danger')); $('saveCanvasViewBtn').onclick=()=>saveCanvasView().catch(err=>setStatus(err.message,'danger')); $('updateCanvasPresenceBtn').onclick=()=>updateCanvasPresence().catch(err=>setStatus(err.message,'danger')); $('refreshCanvasOverlaysBtn').onclick=()=>refreshCanvasOverlays().catch(err=>setStatus(err.message,'danger')); $('saveCanvasOverlayStateBtn').onclick=()=>saveCanvasOverlayState().catch(err=>setStatus(err.message,'danger')); $('adminRefreshBtn').onclick=refreshAdmin; $('refreshEventsBtn').onclick=refreshAdmin; $('refreshIdentitiesBtn').onclick=refreshAdmin; $('refreshUsersBtn').onclick=refreshAdmin; $('reloadConfigBtn').onclick=reloadConfig; $('createUserBtn').onclick=createUser; $('refreshRolesBtn').onclick=refreshAdmin; $('refreshAdminSessionsBtn').onclick=refreshAdmin; $('refreshAdminMemoryBtn').onclick=refreshAdminMemory; $('refreshAdminMetricsBtn').onclick=refreshAdmin; $('refreshAdminToolCallsBtn').onclick=refreshAdmin;
document.querySelectorAll('.tab-btn').forEach(btn=>btn.onclick=()=>{ switchTab(btn.dataset.tab); if(btn.dataset.tab==='builder' && !$('builderCatalog').children.length) refreshBuilderCatalog().catch(()=>{}); if(btn.dataset.tab==='policies' && !$('policySnapshotBox').textContent.trim()) refreshPolicyExplorerSnapshot().catch(()=>{}); if(btn.dataset.tab==='secrets' && !$('secretCatalogBox').children.length) refreshSecretGovernance().catch(()=>{}); if(btn.dataset.tab==='replay' && !$('replaySummaryBox').textContent.trim() && state.currentSessionId) { $('replaySessionId').value=state.currentSessionId; loadSessionReplay(state.currentSessionId).catch(()=>{}); } if(btn.dataset.tab==='operator' && !$('operatorOverview').children.length) { refreshOperatorConsole().then(()=>{ if(state.currentSessionId){ $('operatorSessionId').value=state.currentSessionId; return loadOperatorSession(state.currentSessionId); } }).catch(()=>{}); } if(btn.dataset.tab==='releases' && !$('releaseList').children.length) refreshReleases().catch(()=>{}); if(btn.dataset.tab==='voice' && !$('voiceSessionList').children.length) refreshVoiceSessions().catch(()=>{}); if(btn.dataset.tab==='app' && !$('appInstallationList').children.length) refreshAppFoundation().catch(()=>{}); if(btn.dataset.tab==='canvas' && !$('canvasDocumentList').children.length) refreshCanvasCore().catch(()=>{}); if(btn.dataset.tab==='config' && !$('configFileList').children.length) refreshConfigCenter().catch(()=>{}); });
bootstrapPwa().catch(()=>{});
if(state.baseUrl) connect();
