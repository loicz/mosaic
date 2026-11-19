/* Recorded evacuation rendering plus explicitly synthetic control-state fixtures.
 * This test does not create flight, ranging or personnel evidence. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.MOSAIC_PLAYWRIGHT_PACKAGE||'playwright');
async function main(){
  const [url,record,output]=process.argv.slice(2);
  fs.mkdirSync(output,{recursive:true});
  const rows=fs.readFileSync(record,'utf8').trim().split('\n').map(JSON.parse);
  const frames=rows.filter(r=>r.kind==='state').map(r=>r.value);
  const withdrawing=frames.filter(s=>s.phase==='evacuating'&&s.people.every(p=>p.status==='current'));
  const withdrawal=withdrawing[Math.floor(withdrawing.length*.6)];
  const objective=frames.find(s=>s.phase==='objective_complete'&&!s.evacuation.blocked);
  const holding=frames.find(s=>s.phase==='planning_evacuation');
  const terminal=frames.at(-1);
  assert(withdrawal&&objective&&holding&&terminal.phase==='complete');
  // Auto mode can cross "evacuated" between recorder snapshots. Model only
  // that UI state from the recorded final accountability, without altering logs.
  const exitControl={...terminal,phase:'evacuated'};
  let frame,version=0;const commands=[],errors=[];
  const browser=await chromium.launch({headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  try{
    const page=await browser.newPage({viewport:{width:1536,height:1050}});
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/state',route=>route.fulfill({json:frame}));
    await page.route('**/api/replay*',route=>{
      const index=new URL(route.request().url()).searchParams.get('frame');
      return route.fulfill({json:index===null?{schema:'mosaic.replay.index.v1',frames:frames.map(s=>({time:s.time,phase:s.phase}))}:frames[Number(index)]});
    });
    await page.route('**/api/command',route=>{commands.push(route.request().postDataJSON().op);return route.fulfill({status:202,json:{accepted:true}});});
    async function display(source){
      frame={...source,token:'evacuation-control-fixture-'+(++version)};
      await page.goto(url);await page.waitForSelector('.drone-card');
    }
    await display(objective);
    assert.equal(await page.locator('#primary-action').textContent(),'Start evacuation');
    assert(await page.locator('#recall').isDisabled());
    await page.locator('#primary-action').click();
    await display(holding);
    assert(await page.locator('#recall').isDisabled());
    assert.match(await page.locator('#evacuation-status').textContent(),/West detour/);
    await page.screenshot({path:path.join(output,'coverage-handover.png'),fullPage:true});
    await display(withdrawal);
    assert(await page.locator('#recall').isDisabled());
    assert.match(await page.locator('#phase-description').textContent(),/Tracking everyone/);
    // A held key/focus remains on the same roster node across polling updates.
    await page.locator('[data-person="R2"]').focus();
    await page.waitForTimeout(600);
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.person),'R2');
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('[data-person="R2"]').getAttribute('aria-pressed'),'true');
    await page.screenshot({path:path.join(output,'withdrawal-3d.png'),fullPage:true});
    await display(exitControl);
    assert.equal(await page.locator('#primary-action').textContent(),'Recover fleet');
    assert(await page.locator('#recall').isEnabled());
    await page.locator('#primary-action').click();
    assert.deepEqual(commands,['evacuate','recall']);
    await display(terminal);
    assert.match(await page.locator('#evacuation-status').innerText(),/ALL PERSONNEL ACCOUNTED FOR/);
    await page.locator('#replay-toggle').click();
    await page.locator('#replay-range').fill(String(frames.indexOf(withdrawal)));
    await page.waitForFunction(()=>document.getElementById('phase-label').textContent==='Personnel withdrawing');
    for(const id of ['primary-action','recall','fault-link','fault-anchor','fault-radio','fault-route'])assert(await page.locator('#'+id).isDisabled());
    await page.locator('#view-2d').click();
    await page.screenshot({path:path.join(output,'withdrawal-2d.png'),fullPage:true});
    for(const width of [320,390,768,1024,1920]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow at ${width}`);
    }
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'withdrawal-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,scope:'recorded rendering and synthetic evacuated control fixture; not flight evidence',commands,errors,checks:['evacuate action','recovery locked before exit','coverage status','full-roster accountability','recovery action after exit','stable roster focus','replay lock including route closure','2D/3D','320-1920px layouts']},null,2));
    console.log('PASS evacuation browser controls, rendering, focus, replay, layouts');
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
