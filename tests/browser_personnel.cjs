/* Inspect actual Three.js geometry in Chromium, using a real flight recording. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.MOSAIC_PLAYWRIGHT_PACKAGE || 'playwright');

function crosses(a, b, wall) {
  let low = 0, high = 1;
  for (let axis = 0; axis < 2; axis++) {
    const delta = b[axis] - a[axis];
    if (Math.abs(delta) < 1e-10) {
      if (a[axis] < wall[axis] || a[axis] > wall[axis] + wall[axis + 2]) return false;
    } else {
      const ends = [(wall[axis] - a[axis]) / delta, (wall[axis] + wall[axis + 2] - a[axis]) / delta].sort((x, y) => x - y);
      low = Math.max(low, ends[0]); high = Math.min(high, ends[1]);
      if (low > high) return false;
    }
  }
  return true;
}

async function main() {
  const [url, record, output] = process.argv.slice(2);
  assert(url && record && output, 'usage: node tests/browser_personnel.cjs URL SESSION_JSONL OUTPUT');
  fs.mkdirSync(output, {recursive: true});
  const frames = fs.readFileSync(record, 'utf8').trim().split('\n').map(JSON.parse).filter(r => r.kind === 'state').map(r => r.value);
  // Automatic recall may start before a snapshot captures objective_complete.
  const frame = frames.findLast(s => s.outcome === 'objective_completed');
  assert(frame && frame.people.length === 3, 'completed personnel recording required');
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox', '--enable-unsafe-swiftshader']});
  const errors = [];
  try {
    const page = await browser.newPage({viewport: {width: 1536, height: 1050}});
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error' && /THREE|shader/i.test(m.text())) errors.push(m.text()); });
    // The harness owns this renderer; UI interactions are covered separately.
    await page.route('**/app.js', route => route.fulfill({contentType: 'text/javascript', body: ''}));
    await page.goto(url);
    const geometry = await page.evaluate(async state => {
      await document.fonts.load('14px "JetBrains Mono NF"');
      const {MapView} = await import('/map-view.mjs');
      const view = window.personnelView = new MapView(document.getElementById('map'), document.getElementById('map-container'), () => {});
      view.build(state.scene); view.update(state, 'R1');
      return [...view.people].map(([id, item]) => ({id, segments: item.line.isLineSegments,
        vertices: Array.from(item.line.geometry.attributes.position.array), position: item.group.position.toArray()}));
    }, frame);
    let segmentCount = 0;
    for (const item of geometry) {
      assert(item.segments);
      const person = frame.people.find(p => p.id === item.id);
      assert.deepEqual(item.position, [person.position[0], 0, -person.position[1]], 'solved positions must not be moved');
      for (let i = 0; i < item.vertices.length; i += 6) {
        const a = [item.vertices[i], -item.vertices[i + 2]], b = [item.vertices[i + 3], -item.vertices[i + 5]];
        assert(!frame.scene.walls.some(wall => crosses(a, b, wall)), 'rendered segment intersects a wall');
        segmentCount++;
      }
    }
    assert(segmentCount > 30, 'nonempty real trails required');
    await page.waitForTimeout(200);
    await page.locator('#map').screenshot({path: path.join(output, 'personnel-3d.png')});
    await page.evaluate(() => { window.personnelView.mode = '2d'; });
    await page.waitForTimeout(100);
    await page.locator('#map').screenshot({path: path.join(output, 'personnel-2d.png')});
    const fixture = structuredClone(frame);
    for (const person of fixture.people) {
      person.position = [13, 8.1];
      person.trail = [[16.8, 6], [16.8, 7], null, [13, 7], [13, 9], [13, 10]];
    }
    const gaps = await page.evaluate(state => {
      const view = window.personnelView; view.update(state, 'R1');
      return [...view.people.values()].map(item => ({vertices: Array.from(item.line.geometry.attributes.position.array),
        position: item.group.position.toArray(), dashed: item.line.material.isLineDashedMaterial,
        distances: item.line.geometry.attributes.lineDistance?.count}));
    }, fixture);
    for (const item of gaps) {
      assert.equal(item.vertices.length, 12, 'only two observed unobstructed segments may remain');
      assert.deepEqual(item.position, [13, 0, -8.1]);
      if (item.dashed) assert.equal(item.distances, 4);
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({passed: true,
      evidence_type: 'Chromium renders authentic recorded fixes; separate synthetic wall/gap regression',
      rendered_segments: segmentCount, errors, checks: ['no rendered wall crossings', 'unchanged solved positions',
        'missing-fix gaps', 'wall-conflict gaps', 'solid and dashed segment geometry', '2D and 3D rendering']}, null, 2) + '\n');
    console.log(`PASS personnel renderer: ${segmentCount} recorded segments, gap and wall regressions`);
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
