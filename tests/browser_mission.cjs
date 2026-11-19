/* Real Chromium checks against the running PX4/Gazebo command console. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.MOSAIC_PLAYWRIGHT_PACKAGE||'playwright');
async function main(){
  const url=process.argv[2]||'http://127.0.0.1:8766';
  const output=process.argv[3]||'/tmp/mosaic-mission-browser';fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1536,height:1050},deviceScaleFactor:1});
  const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error'&&/THREE|shader/i.test(m.text()))errors.push(m.text());});
  page.on('request',request=>{if(!request.url().startsWith(url)&&!request.url().startsWith('data:'))external.push(request.url());});
  try{
    await page.goto(url);await page.waitForSelector('.drone-card');
    if(process.argv.includes('--wait-tracking'))await page.waitForFunction(()=>['Personnel mission active','Objective reached','Preparing evacuation','Personnel withdrawing'].includes(document.getElementById('phase-label').textContent),{},{timeout:300000});
    await page.waitForTimeout(1500);
    await page.evaluate(()=>document.fonts.ready);
    assert(await page.evaluate(()=>document.fonts.check('12px "JetBrains Mono NF"')),'bundled font unavailable');
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    const assertEnglish=async()=>assert.equal(await page.evaluate(()=>/\p{Script=Han}/u.test(document.body.innerText + [...document.querySelectorAll('[aria-label], [title]')].map(e=>(e.getAttribute('aria-label')||'')+(e.getAttribute('title')||'')).join(''))),false,'non-English interface text');
    await assertEnglish();
    assert.match(await page.locator('#roster').innerText(), /ETHAN CROSS|Ethan Cross/);
    assert.match(await page.locator('#roster').innerText(), /SLOANE VOSS|Sloane Voss/);
    assert.match(await page.locator('#roster').innerText(), /ADRIAN KNOX|Adrian Knox/);
    await page.locator('#glow-toggle').click();
    assert.equal(await page.locator('#glow-toggle').getAttribute('aria-pressed'),'false');
    await page.locator('#glow-toggle').click();
    assert.equal(await page.locator('#glow-toggle').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('.fault-area').getAttribute('open'),null,'fault controls should start collapsed');
    await page.locator('.fault-area summary').focus();
    await page.keyboard.press('Enter');
    assert(await page.locator('#fault-link').isVisible(),'keyboard cannot expand faults');
    await assertEnglish();
    await page.locator('.fault-area summary').click();
    assert.equal(await page.locator('#map-error').isVisible(),false,'WebGL failed');
    assert.equal(await page.locator('.drone-card').count(),6);
    await page.locator('#view-2d').click();assert.equal(await page.locator('#view-2d').getAttribute('aria-pressed'),'true');
    await page.screenshot({path:path.join(output,'desktop-2d.png'),fullPage:true});
    await page.locator('#view-3d').click();
    await page.locator('[data-person="R2"]').click();assert.equal(await page.locator('[data-person="R2"]').getAttribute('aria-pressed'),'true');
    await page.screenshot({path:path.join(output,'desktop-3d.png'),fullPage:true});
    await page.locator('#replay-toggle').click();await page.waitForSelector('#replay-banner:visible');
    for(const id of ['primary-action','recall','fault-link','fault-anchor','fault-radio','fault-route'])assert(await page.locator('#'+id).isDisabled(),'replay must lock '+id);
    await assertEnglish();
    await page.locator('#replay-range').fill('2');
    await page.locator('#replay-toggle').click();
    // A lost HTTP connection must expire the visible people, even when PX4
    // and the mission continue independently of this browser.
    await page.route('**/api/state',route=>route.abort());
    await page.waitForFunction(()=>document.getElementById('link-status').textContent==='Console offline');
    assert.equal(await page.locator('#primary-action').isDisabled(),true);
    assert.equal(await page.locator('.person-state:not(.stale)').filter({hasText:'[+]'}).count(),0);
    await page.unroute('**/api/state');
    await page.waitForFunction(()=>document.getElementById('link-status').textContent!=='Console offline');
    const state=await (await page.request.get(url+'/api/state')).json();
    // Freeze an authentic frame behind successful HTTP responses. A resumed
    // HTTP connection with that same frame must not revive expired positions.
    let frozen=structuredClone(state), frozenResponses=0;
    await page.route('**/api/state',route=>{frozenResponses++;return route.fulfill({json:frozen});});
    const frozenAt=Date.now();
    await page.waitForFunction(()=>document.getElementById('link-status').textContent==='Simulation paused / stale',{},{timeout:3000});
    assert(Date.now()-frozenAt<=3000);
    assert.equal(await page.locator('.person-state:not(.stale)').filter({hasText:'[+]'}).count(),0);
    assert(frozenResponses>=2);
    await page.unroute('**/api/state');
    await page.route('**/api/state',route=>route.abort());
    await page.waitForFunction(()=>document.getElementById('link-status').textContent==='Console offline');
    await page.unroute('**/api/state');
    await page.route('**/api/state',route=>route.fulfill({json:frozen}));
    await page.waitForTimeout(500);
    assert.equal(await page.locator('.person-state:not(.stale)').filter({hasText:'[+]'}).count(),0);
    // Clock-only advancement still supplies no new personnel observation.
    frozen.time+=.2;
    await page.waitForTimeout(500);
    assert.equal(await page.locator('.person-state:not(.stale)').filter({hasText:'[+]'}).count(),0);
    await page.unroute('**/api/state');
    await page.waitForFunction(()=>document.getElementById('link-status').textContent==='Link online');
    assert.equal((await page.request.post(url+'/api/command',{data:{op:'deploy'}})).status(),403);
    assert.equal((await page.request.post(url+'/api/command',{headers:{'X-Mosaic-Token':state.token,Origin:'https://invalid.example'},data:{op:'deploy'}})).status(),403);
    await page.setViewportSize({width:390,height:844});await page.waitForTimeout(500);
    await assertEnglish();
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    assert.equal(overflow,false,'mobile horizontal overflow');
    await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    for(const width of [320,768,1024,1920]){
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`horizontal overflow at ${width}px`);
    }
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,errors,external,frozenResponses,checks:['3D rendering','2D toggle','roster selection','real recording replay','replay command lock','HTTP loss expires positions','frozen HTTP 200 expires positions within 3 seconds','old frame after reconnection stays expired','clock advancement alone cannot renew observations','command token validation','cross-origin rejection','mobile overflow','offline resources','English labels and accessible names','bundled JetBrains Mono Nerd Font','Western operative identities','phosphor rendering toggle','no WebGL shader errors','keyboard fault disclosure','all replay controls locked','320/390/768/1024/1536/1920px layout']},null,2));
    console.log('PASS mission browser: WebGL, views, selection, replay, mobile, offline assets');
  }catch(error){
    fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({error:String(error),label:await page.locator('#link-status').textContent().catch(()=>null),phase:await page.locator('#phase-label').textContent().catch(()=>null),errors},null,2));
    throw error;
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
