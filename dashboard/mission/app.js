import {MapView} from './map-view.mjs';
import {Freshness} from './freshness.mjs';
import {phaseText, droneText, statusText, personnelName, eventText} from './ui-text.mjs';

const $=id=>document.getElementById(id);
const elapsed=t=>`${Math.floor(t/60).toString().padStart(2,'0')}:${Math.floor(t%60).toString().padStart(2,'0')}`;
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let live=null,shown=null,selected='R1',replaying=false,frames=[],mode='3d',sceneId=null,model=null;
let lastEvents='',busy=false;
let indexedReplay=false,replayRequest=0;
const freshness=new Freshness();
const rosterButtons=new Map();

function toast(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,3500);}
async function command(op){
  if(replaying||!live?.token)return;
  try{const response=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','X-Mosaic-Token':live.token},body:JSON.stringify({op})});if(!response.ok)throw Error('Command was not accepted');}
  catch(error){toast(error.message);}
}

try{model=new MapView($('map'),$('map-container'),person=>{selected=person;draw(shown);});}catch(error){$('map-error').hidden=false;console.error(error);}
$('glow-toggle').onclick=()=>{
  if(!model)return;
  model.effects=!model.effects;
  $('glow-toggle').textContent=model.effects?'GLOW ON':'GLOW OFF';
  $('glow-toggle').setAttribute('aria-pressed',String(model.effects));
  document.body.classList.toggle('glow-off',!model.effects);
};

function draw(state){
  if(!state?.scene){$('phase-label').textContent=phaseText[state?.phase]||'Connecting';return;}
  shown=state;if(sceneId!==state.scene.id&&model){model.build(state.scene);sceneId=state.scene.id;}
  $('clock').textContent=elapsed(state.time);$('phase-label').textContent=phaseText[state.phase]||state.phase;
  $('link-status').textContent=replaying?'History':state.console_status==='offline'?'Console offline':state.console_status==='paused'?'Simulation paused / stale':state.link?'Link online':`Link lost / ${Math.ceil(state.reconnect_in)}s`;
  $('link-status').classList.toggle('off',!state.link);$('link-banner').hidden=state.link||replaying;
  $('replay-banner').hidden=!replaying;
  const step={starting:0,idle:0,deploying:0,ready:1,tracking:2,objective_complete:2,planning_evacuation:3,evacuating:3,evacuated:3,recalling:4,complete:5}[state.phase]||0;
  document.querySelectorAll('.steps li').forEach((li,i)=>{li.classList.toggle('active',i===step);li.classList.toggle('done',i<step);if(i===step)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');});
  const description={starting:'Connecting flight controllers and onboard sensors.',idle:'Drones enter, find clear routes and establish positioning anchors.',deploying:'Drones follow navigable routes with local lidar replanning.',ready:'Anchor coordinates estimated. Waiting for personnel entry.',tracking:'Personnel remain inside. Positioning nodes stay on site.',objective_complete:'Indoor objective reached. Start personnel evacuation before recovering the fleet.',planning_evacuation:'Personnel hold at the objective while withdrawal coverage is checked.',evacuating:'Tracking everyone along the withdrawal route. Fleet recovery remains locked.',evacuated:'All enrolled personnel accounted for at the outdoor assembly area.',recalling:'Personnel evacuation confirmed. Nodes return to base in sequence.',complete:'All deployed drones returned. The mission is ready for replay.'};
  $('phase-description').textContent=description[state.phase]||'';
  const action={idle:['Deploy fleet','deploy'],ready:['Start personnel task','task'],objective_complete:['Start evacuation','evacuate'],evacuated:['Recover fleet','recall']};
  const next=action[state.phase];$('primary-action').textContent=next?next[0]:state.phase==='complete'?'Recovery complete':state.phase==='starting'?'Preparing...':'Mission running';
  $('primary-action').disabled=!next||!state.link||replaying;$('primary-action').onclick=()=>next&&command(next[1]);
  $('recall').disabled=!['ready','evacuated'].includes(state.phase)||!state.link||replaying;
  const evacuation=state.evacuation;
  $('evacuation-status').hidden=!evacuation?.plan;
  const coverageText={checking:'Checking route coverage',positioning:'Moving an anchor; current personnel coverage retained',verifying:'Verifying fresh ranging before departure',ready:'Withdrawal coverage verified',waiting_for_observations:'Waiting for fresh observations and command link',coverage_unavailable:'Coverage unavailable. Personnel hold; fleet recovery locked'};
  if(evacuation?.plan)$('evacuation-status').textContent=evacuation.completed_at!=null?`ALL PERSONNEL ACCOUNTED FOR / ${elapsed(evacuation.completed_at)} / ${evacuation.plan.label}`:`${evacuation.plan.label} / ${coverageText[evacuation.status]||'Checking coverage'}${evacuation.coverage?` / Route minimum: ${evacuation.coverage.minimum_nodes} ranging nodes`:''}`;
  $('anchor-count').innerHTML=`${state.active_anchors}<small>/ ${state.scene.drones.length}</small>`;
  const current=state.people.filter(p=>p.status==='current').length;
  $('people-count').innerHTML=`${state.people.length?current:'--'}<small>/ ${state.scene.roster.length}</small>`;
  $('inference-count').innerHTML=`${state.drones.reduce((sum,d)=>sum+(d.inferences||0),0).toLocaleString('en-US')}`;
  const remaining=state.drones.filter(d=>['anchor','radio_failed','calibrating'].includes(d.state)).length;
  $('remaining-count').textContent=state.link?remaining:'--';
  if(!rosterButtons.size)$('roster').textContent='';
  for(const person of state.scene.roster){
    const p=state.people.find(p=>p.id===person.id);
    let button=rosterButtons.get(person.id);
    if(!button){
      button=document.createElement('button');button.className='person';button.dataset.person=person.id;
      button.innerHTML='<span class="person-icon"></span><span class="person-info"><strong></strong><small></small></span><span class="person-state"></span>';
      button.onclick=()=>{selected=person.id;draw(shown);};
      rosterButtons.set(person.id,button);$('roster').append(button);
    }
    button.classList.toggle('selected',person.id===selected);button.setAttribute('aria-pressed',String(person.id===selected));
    button.querySelector('.person-icon').textContent=person.id;
    button.querySelector('strong').textContent=personnelName(person);
    button.querySelector('small').textContent=p?statusText[p.status]:'Enrolled / Awaiting entry';
    const status=button.querySelector('.person-state');status.classList.toggle('stale',Boolean(p&&p.status!=='current'));
    status.textContent=p?(p.status==='current'?'[+]':`${p.age.toFixed(0)}s`):'--';
  }
  const person=state.people.find(p=>p.id===selected);$('person-detail').hidden=!person;
  if(person)$('person-detail').textContent=`${selected} / ${statusText[person.status]} / ${person.used.length} ranging nodes${person.allowance?` / Allowance ${person.allowance.toFixed(2)}m`:''}. Estimated position; not independently verified. Trail gaps indicate missing fixes or wall conflicts.`;
  $('fleet').innerHTML=state.drones.map(d=>`<div class="drone-card ${d.stale?'stale':d.state==='anchor'||d.armed?'active':''}"><strong>${escape(d.id)}</strong><i class="drone-dot"></i><small>${d.stale?`Last seen / ${Math.round(d.age)}s`:escape(droneText[d.state]||d.state)}</small></div>`).join('');
  $('fault-link').disabled=replaying||state.phase==='starting'||state.phase==='complete';$('fault-link').textContent=state.link?'Disconnect link':'Reconnect link';$('fault-link').classList.toggle('active',!state.link);
  $('fault-anchor').disabled=replaying||state.active_anchors<4||Boolean(state.failed);$('fault-anchor').textContent=state.failed?`${state.failed} disabled`:'Disable one anchor';
  $('fault-radio').disabled=replaying||!['tracking','objective_complete','planning_evacuation','evacuating'].includes(state.phase);$('fault-radio').textContent=state.interference?'Clear ranging interference':'Add ranging interference';$('fault-radio').classList.toggle('active',state.interference);
  $('fault-route').disabled=replaying||state.phase!=='objective_complete'||Boolean(evacuation?.blocked)||state.drones.some(d=>['takeoff','transit','landing','calibrating'].includes(d.state));
  $('fault-route').textContent=evacuation?.blocked?'East passage closed':'Close east passage';
  if(!replaying&&state.console_status&&state.console_status!=='live'){
    for(const id of ['fault-link','fault-anchor','fault-radio','fault-route'])$(id).disabled=true;
  }
  const eventKey=state.events.map(e=>e.sequence).join(',');if(eventKey!==lastEvents){lastEvents=eventKey;$('events').innerHTML=state.events.slice(-4).reverse().map(e=>`<div class="event"><time>${elapsed(e.time)}</time><span>${escape(eventText(e))}</span></div>`).join('');}
  model?.update(state,selected);
}
$('recall').onclick=()=>command('recall');$('fault-link').onclick=()=>command(live?.link?'disconnect':'reconnect');$('fault-anchor').onclick=()=>command('fail_anchor');$('fault-radio').onclick=()=>command('interference');
$('fault-route').onclick=()=>command('block_route');
function setView(value){mode=value;if(model)model.mode=value;document.querySelector('.map-hint').hidden=value==='2d';for(const v of ['2d','3d']){$('view-'+v).classList.toggle('selected',v===value);$('view-'+v).setAttribute('aria-pressed',String(v===value));}model?.size();}
$('view-2d').onclick=()=>setView('2d');$('view-3d').onclick=()=>setView('3d');
async function showReplay(index){
  const request=++replayRequest;
  try{
    let frame=frames[index];
    if(indexedReplay){const response=await fetch(`/api/replay?frame=${index}`);if(!response.ok)throw Error();frame=await response.json();}
    if(replaying&&request===replayRequest)draw(frame);
  }catch{if(replaying&&request===replayRequest)toast('Unable to load this recorded frame.');}
}
$('replay-toggle').onclick=async()=>{
  if(replaying){replaying=false;++replayRequest;$('replay-toggle').textContent='[ REPLAY ]';$('replay-range').disabled=true;$('record-status').textContent='[ REC ]';draw(live);return;}
  $('replay-toggle').disabled=true;
  try{
    const response=await fetch('/api/replay');if(!response.ok)throw Error();
    const recording=await response.json();indexedReplay=recording.schema==='mosaic.replay.index.v1';
    frames=indexedReplay?recording.frames:recording;
    if(!frames.length){toast('No mission recording yet.');return;}
    replaying=true;$('replay-toggle').textContent='[ LIVE ]';$('replay-range').disabled=false;
    $('replay-range').max=String(frames.length-1);$('replay-range').value='0';$('record-status').textContent='[ HISTORY ]';
    // Lock controls immediately while the first historical frame loads.
    draw(shown);await showReplay(0);
  }catch{toast('Unable to load the mission recording.');}
  finally{$('replay-toggle').disabled=false;}
};
$('replay-range').oninput=()=>showReplay(Number($('replay-range').value));
async function poll(){
  if(busy)return;busy=true;
  try{
    const response=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(1500)});
    if(!response.ok)throw Error();
    live=freshness.accept(await response.json(),performance.now());
    $('link-banner').textContent=live.console_status==='live'?'LINK LOST / Last-known positions':'STALE DATA / Last-known positions';
    if(!replaying)draw(live);
  }catch{
    freshness.failed();
    if(!replaying&&live?.scene){
      live=freshness.view(live,performance.now());draw(live);
      $('link-banner').hidden=false;$('link-banner').textContent='OFFLINE / Last-known positions';
    }
    if(!replaying){$('link-status').textContent='Console offline';$('link-status').classList.add('off');}
  }finally{busy=false;}
}
await document.fonts.load('14px "JetBrains Mono NF"');
poll();setInterval(poll,250);
// Expiry is a display deadline, independent of the next HTTP response. A slow
// request or a frozen successful stream must not prolong a current-position badge.
setInterval(()=>{
  if(replaying||!live?.scene)return;
  const current=freshness.view(live,performance.now());
  if(current.console_status!==live.console_status||
     current.people.some((p,i)=>p.status!==live.people[i].status)||
     current.drones.some((d,i)=>d.stale!==live.drones[i].stale)){
    live=current;draw(live);
    if(live.console_status==='paused')$('link-banner').textContent='STALE DATA / Last-known positions';
  }
},100);
