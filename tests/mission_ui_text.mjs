import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {eventText, personnelName, droneText} from '../dashboard/mission/ui-text.mjs';

const scene = JSON.parse(readFileSync(new URL('../config/mission-rescue.json', import.meta.url)));
const before = JSON.stringify(scene);
assert.deepEqual(scene.roster.map(personnelName), ['Ethan Cross / GHOST', 'Sloane Voss / VIPER', 'Adrian Knox / WRAITH']);
assert.equal(JSON.stringify(scene), before, 'display must preserve original scene metadata');
assert.equal(personnelName({id:'R4',name:'Alex / Medic'}), 'Alex / Medic');

assert.equal(personnelName({id:'R4'}), 'Personnel / R4');

const recordedEvents = [
  [{code:'interference',text:'Single-link ranging interference enabled.'}, 'Single-link ranging interference enabled.'],
  [{code:'interference',text:'Ranging interference cleared.'}, 'Ranging interference cleared.'],
  [{code:'command_rejected',text:'Command link unavailable. Command was not sent.'}, 'Command link unavailable. Command was not sent.'],
  [{code:'command_rejected',text:'Command unavailable in this phase.'}, 'Command unavailable in this phase.'],
  [{code:'anchor_failed',text:'D3 ranging timed out. The anchor was excluded and a replacement scheduled.'}, 'D3 ranging timed out. Excluded; replacement scheduled.'],
  [{code:'drone_state',text:'D6 / perch_rejected'}, 'D6 / Perch rejected'],
];
for (const [event, expected] of recordedEvents) {
  const original = structuredClone(event);
  assert.equal(eventText(event), expected);
  assert.deepEqual(event, original, 'do not rewrite recorded evidence');
}
assert.equal(eventText({code:'future',text:'A new event.'}), 'A new event.');
assert.match(eventText({code:'future',text:null}), /details unavailable/);
assert.equal(droneText.perch_rejected, 'Perch rejected');

// Every event code currently emitted by the runtime needs a display translation.
const runtime = readFileSync(new URL('../scripts/mission_runtime.py', import.meta.url), 'utf8');
for (const [,code] of runtime.matchAll(/self\.event\('([^']+)'/g)) {
  if (['interference','command_rejected'].includes(code)) continue; // Both variants checked above.
  const text = eventText({code,text:'D2 / anchor'});
  assert(!/details unavailable|\p{Script=Han}/u.test(text), `missing English event: ${code}`);
}
console.log('PASS English UI: roster, event coverage, recorded outcomes, immutable evidence');
