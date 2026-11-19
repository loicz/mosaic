import assert from 'node:assert/strict';
import {trailSegments} from '../dashboard/mission/trail-segments.mjs';

const wall = [[8.5, 8, 7, .2]];
assert.deepEqual(trailSegments([[12.6, 6], [13.5, 10.4]], wall), [], 'original wall crossing must not be drawn');
assert.deepEqual(trailSegments([[13, 7.9], [13, 8.1], [13, 8.3]], wall), [], 'inside-wall fixes cannot connect');
assert.deepEqual(trailSegments([[13, 8], [14, 8]], wall), [], 'wall boundary is blocked');
const door = [[16.8, 7.9], [16.8, 8.3], [16.8, 9]];
assert.deepEqual(trailSegments(door, wall), [door[0], door[1], door[1], door[2]]);
const gap = [[16.8, 7], null, [16.8, 9], [16.8, 10]];
assert.deepEqual(trailSegments(gap, wall), [gap[2], gap[3]], 'missing fixes must break the trail');
assert.deepEqual(trailSegments([null, null, [1, 1]], wall), []);
assert.deepEqual(trailSegments([], wall), []);
// The source observations, including conflicts and gaps, remain unchanged.
const original = structuredClone(gap);
trailSegments(gap, wall);
assert.deepEqual(gap, original);
console.log('PASS personnel trails: walls, doorways, missing fixes, preserved observations');
