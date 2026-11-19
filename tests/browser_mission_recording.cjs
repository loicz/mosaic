/* English presentation checks using authentic recorded states, not a new flight. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.MOSAIC_PLAYWRIGHT_PACKAGE||'playwright');
async function main(){
  const [url,record,output]=process.argv.slice(2);
  assert(url&&record&&output,'usage: node tests/browser_mission_recording.cjs URL SESSION_JSONL OUTPUT');
  fs.mkdirSync(output,{recursive:true});
  const frames=fs.readFileSync(record,'utf8').trim().split('\n').map(JSON.parse).filter(r=>r.kind==='state').map(r=>r.value);
  const terminal=frames.at(-1);
  assert.equal(terminal.phase,'complete');
  // Entry fixes can overlap within centimeters. Pick a real frame with separable targets.
  const tracking=frames.find(s=>s.phase==='tracking'&&!s.failed&&s.people.length===3&&s.people.every(p=>p.status==='current'&&s.people.every(q=>q.id===p.id||Math.hypot(p.position[0]-q.position[0],p.position[1]-q.position[1])>.6)));
  assert(tracking,'recording must contain current fixes for every enrolled person');
  const phases=[...new Set(frames.map(s=>s.phase))];
  assert(phases.includes('recalling')&&phases.includes('deploying'));
  const events=[...new Map(frames.flatMap(s=>s.events).map(e=>[e.sequence,e])).values()];
  assert(events.some(e=>e.code==='link_lost')&&events.some(e=>e.code==='anchor_failed'),'fault recording required');
  // Real recordings deliberately omit credentials. This token is used only by the intercepted fixture.
  const displayedEvents=[...new Map(frames.flatMap(s=>s.events.slice(-4)).map(e=>[e.sequence,e])).values()];
  let frame={...tracking,token:'recording-test-only'};
  const errors=[],external=[],commands=[];
  const browser=await chromium.launch({headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  try{
    const page=await browser.newPage({viewport:{width:1536,height:1050}});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>{if(m.type()==='error'&&/THREE|shader/i.test(m.text()))errors.push(m.text());});
    page.on('request',r=>{if(!r.url().startsWith(url)&&!r.url().startsWith('data:'))external.push(r.url());});
    await page.addInitScript(()=>{
      window.mapLabels=[];
      const fill=CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.mapLabels.push({text,font:this.font});return fill.call(this,text,...args);};
    });
    await page.route('**/api/state',route=>route.fulfill({json:frame}));
    await page.route('**/api/replay',route=>route.fulfill({json:frames}));
    // Exercise UI commands without injecting additional faults into the source flight.
    await page.route('**/api/command',route=>{
      commands.push(route.request().postDataJSON().op);
      assert(route.request().headers()['x-mosaic-token']);
      return route.fulfill({status:202,json:{accepted:true}});
    });
    await page.goto(url);
    await page.waitForSelector('.drone-card');
    await page.evaluate(()=>document.fonts.ready);
    assert.equal(await page.locator('#map-error').isVisible(),false);
    const english=async()=>{
      assert(!/\p{Script=Han}/u.test(await page.locator('body').innerText()),'Chinese visible in the interface');
      assert(await page.evaluate(()=>[...document.querySelectorAll('body,button,input,summary')].every(e=>getComputedStyle(e).fontFamily.includes('JetBrains Mono NF'))),'inconsistent UI font');
    };
    await english();
    const labels=await page.evaluate(()=>window.mapLabels);
    assert(labels.some(l=>l.text==='WEST WING')&&labels.some(l=>l.text==='RALLY'));
    assert(labels.every(l=>!(/\p{Script=Han}/u.test(l.text))&&l.font.includes('JetBrains Mono NF')),'map labels must use English and the bundled font');
    await page.locator('.fault-area summary').click();
    for(const id of ['fault-link','fault-anchor','fault-radio'])await Promise.all([
      page.waitForResponse(r=>r.url().endsWith('/api/command')&&r.status()===202),
      page.locator('#'+id).click(),
    ]);
    assert.deepEqual(commands,['disconnect','fail_anchor','interference']);
    await page.screenshot({path:path.join(output,'fault-controls.png'),fullPage:true});
    await page.locator('#replay-toggle').click();
    await page.waitForSelector('#replay-banner:visible');
    for(const phase of phases){
      const index=frames.findIndex(s=>s.phase===phase);
      await page.locator('#replay-range').fill(String(index));
      await english();
      for(const id of ['primary-action','recall','fault-link','fault-anchor','fault-radio'])assert(await page.locator('#'+id).isDisabled());
    }
    // Freeze an authentic tracking frame in replay for deterministic map interaction checks.
    const trackingIndex=frames.indexOf(tracking);
    await page.locator('#replay-range').fill(String(trackingIndex));
    await page.locator('#view-2d').click();
    await page.waitForTimeout(150);
    const rect=await page.locator('#map').boundingBox();
    const half=Math.max(11.5,15/(rect.width/rect.height));
    const person=tracking.people.find(p=>p.id==='R3');
    await page.mouse.click(rect.x+rect.width/2+(person.position[0]-13)*rect.height/(2*half),rect.y+rect.height/2-(person.position[1]-9.5)*rect.height/(2*half));
    assert.equal(await page.locator('[data-person="R3"]').getAttribute('aria-pressed'),'true','map person picking');
    await page.locator('#view-3d').click();
    await page.mouse.move(0,0);
    await page.waitForTimeout(150);
    const before=await page.locator('#map').screenshot();
    await page.waitForTimeout(250);
    assert(before.equals(await page.locator('#map').screenshot()),'frozen mission geometry must stay static without decorative motion');
    assert.equal(await page.evaluate(()=>document.getAnimations().length),0,'no decorative DOM animation');
    await page.mouse.move(rect.x+rect.width*.6,rect.y+rect.height*.7);
    await page.mouse.down();await page.mouse.move(rect.x+rect.width*.6+70,rect.y+rect.height*.7+20,{steps:5});await page.mouse.up();
    await page.waitForTimeout(150);
    const orbited=await page.locator('#map').screenshot();
    assert(!before.equals(orbited),'orbit must change the rendered map');
    await page.mouse.wheel(0,150);await page.waitForTimeout(150);
    assert(!orbited.equals(await page.locator('#map').screenshot()),'wheel zoom must change the rendered map');
    await page.locator('#glow-toggle').click();await page.waitForTimeout(150);
    assert.equal(await page.locator('#glow-toggle').getAttribute('aria-pressed'),'false');
    const noGlow=await page.locator('#map').screenshot();
    await page.locator('#glow-toggle').click();await page.waitForTimeout(150);
    assert(!noGlow.equals(await page.locator('#map').screenshot()),'glow toggle must change the rendered map');
    // Render every event reachable in the four-entry log, including fault and recovery messages.
    for(const event of displayedEvents){
      const index=frames.findIndex(s=>s.events.slice(-4).some(e=>e.sequence===event.sequence));
      assert(index>=0,`event ${event.sequence} missing from displayed history`);
      await page.locator('#replay-range').fill(String(index));
      await english();
      assert(!/translation unavailable/.test(await page.locator('#events').innerText()),`untranslated event ${event.code}`);
    }
    await page.locator('#replay-range').fill(String(frames.length-1));
    assert.equal(await page.locator('#remaining-count').innerText(),'0');
    assert.match(await page.locator('#anchor-count').innerText(),/^0\s*\/\s*5$/);
    await page.screenshot({path:path.join(output,'terminal-replay.png'),fullPage:true});
    frame=terminal;
    await page.locator('#replay-toggle').click();
    await page.waitForFunction(()=>document.getElementById('phase-label').textContent==='Mission complete');
    await english();
    // The same disclosure remains usable at the narrowest supported width.
    await page.setViewportSize({width:320,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(output,'mobile-fault-controls.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,evidence_type:'Chromium presentation of authentic recorded simulation states; command responses intercepted',phases,displayed_events_checked:displayedEvents.length,recorded_events:events.length,map_labels:labels.map(l=>l.text),commands,errors,external,checks:['English text across recorded phases and events','English canvas labels','2D map personnel picking','3D pointer orbit','wheel zoom','no decorative motion in frozen scene','phosphor toggle changes rendered pixels','no WebGL shader errors','consistent bundled font','fault button command routing','replay locks every command','terminal zero remaining nodes','expanded faults at 320px']},null,2)+'\n');
    console.log('PASS recorded English interface: phases, events, canvas fonts, commands, terminal, narrow faults');
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
