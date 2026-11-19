import assert from 'node:assert/strict';
import {Freshness} from '../dashboard/mission/freshness.mjs';

const frame = (time=10, stamp=time) => ({time, token:'session', link:true,
  drones:[{id:'D1', time:stamp, age:0, anchor:[1,2,.5], stale:false}],
  people:[{id:'R1', time:stamp, age:0, status:'current'}]});
const freshness = new Freshness();
assert.equal(freshness.accept(frame(), 0).people[0].status, 'current');
for(let wall=250; wall<=3000; wall+=250) freshness.accept(frame(), wall);
let value=freshness.accept(frame(), 3000);
assert.equal(value.console_status, 'paused');
assert.equal(value.link, false);
assert.equal(value.people[0].status, 'last_known');
assert.equal(value.active_anchors, 0);
value=freshness.accept(frame(11,10), 3100);
assert.equal(value.people[0].status, 'last_known', 'advancing clock cannot refresh old observations');
value=freshness.accept(frame(11.2), 3200);
assert.equal(value.people[0].status, 'current');
freshness.failed();
assert.equal(freshness.accept(frame(11.2), 3250).people[0].status, 'last_known');
assert.equal(freshness.accept(frame(11.3,11.2), 3300).people[0].status, 'last_known');
assert.equal(freshness.accept(frame(11.4), 3350).people[0].status, 'current');
assert.equal(freshness.accept(frame(9), 3400).people[0].status, 'last_known', 'out of order observations cannot become current');
console.log('PASS: frozen HTTP 200, frozen observations, transport recovery, fresh recovery, old packets');
