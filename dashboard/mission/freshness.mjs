// HTTP success alone cannot renew an observation or a stopped simulation clock.
export class Freshness {
  constructor() {
    this.clock = {stamp: -Infinity, wall: 0, invalid: false};
    this.observations = new Map();
    this.offline = false;
    this.token = null;
  }
  failed() {
    this.offline = true;
    this.clock.invalid = true;
    for (const value of this.observations.values()) value.invalid = true;
  }
  accept(state, now) {
    if (this.token !== null && state.token && state.token !== this.token) {
      this.clock = {stamp: -Infinity, wall: now, invalid: false};
      this.observations.clear();
    }
    if (state.token) this.token = state.token;
    if (state.time > this.clock.stamp) {
      this.clock = {stamp: state.time, wall: now, invalid: false};
      this.offline = false;
    }
    for (const [kind, rows] of [['drone', state.drones || []], ['person', state.people || []]]) {
      for (const row of rows) {
        const key = `${kind}:${row.id}`, previous = this.observations.get(key);
        if (!previous || row.time > previous.stamp) {
          this.observations.set(key, {stamp: row.time, wall: now, invalid: false});
        }
      }
    }
    return this.view(state, now);
  }
  view(state, now) {
    const value = structuredClone(state);
    const paused = this.clock.invalid || state.time < this.clock.stamp || now-this.clock.wall >= 2500;
    value.console_status = this.offline ? 'offline' : paused ? 'paused' : 'live';
    if (paused || this.offline) value.link = false;
    for (const [kind, rows] of [['drone', value.drones || []], ['person', value.people || []]]) {
      for (const row of rows) {
        const seen = this.observations.get(`${kind}:${row.id}`);
        const elapsed = seen ? (now-seen.wall)/1000 : 0;
        const expired = paused || this.offline || !seen || seen.invalid || row.time < seen.stamp || elapsed >= 2.5;
        row.age = Math.max(row.age || 0, value.time-row.time, elapsed);
        if (expired || row.age > 1.5) {
          if (kind === 'drone') row.stale = true;
          else row.status = 'last_known';
        }
      }
    }
    value.active_anchors = (value.drones || []).filter(d => d.anchor && !d.stale).length;
    return value;
  }
}
