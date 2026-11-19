// Display labels for the mission console and replay.
export const phaseText = {
  starting: 'Starting simulation', idle: 'Awaiting deployment', deploying: 'Deploying fleet',
  ready: 'Network ready', tracking: 'Personnel mission active', objective_complete: 'Objective reached',
  planning_evacuation: 'Preparing evacuation', evacuating: 'Personnel withdrawing', evacuated: 'Personnel accounted for',
  recalling: 'Recovering fleet', complete: 'Mission complete',
};
export const droneText = {
  boot: 'Booting', idle: 'Standby', takeoff: 'Taking off', transit: 'In transit',
  landing: 'Approaching perch', calibrating: 'Calibrating', anchor: 'Anchor online',
  radio_failed: 'Ranging failed', returned: 'Returned', perch_rejected: 'Perch rejected',
};
export const statusText = {
  current: 'Current position', uncertain: 'Uncertain position', last_known: 'Last-known position',
};
const printableEnglish = value => typeof value === 'string' && /^[\x20-\x7e]+$/.test(value);
export const personnelName = person => printableEnglish(person.name) ? person.name :
  `Personnel / ${printableEnglish(person.id) ? person.id : 'Unknown'}`;
const events = {
  boot: 'Flight controllers and onboard processors starting.',
  link_lost: 'Command link lost. Onboard missions continue.',
  link_restored: 'Link restored. Onboard progress synchronized.',
  deploy: 'Autonomous deployment started: sensing, placement, calibration.',
  task: 'Personnel entered. Position and trail recording started.',
  recall: 'Recovering nodes sequentially to the launch area.',
  ready_to_deploy: 'Fleet ready. Autonomous deployment available.',
  network_ready: 'Positioning network ready. Personnel may enter.',
  complete: 'All deployed nodes returned. No nodes remain on site.',
  service_restored: 'Fresh fixes sustained for all personnel for 5s. Replacement continues.',
  objective: 'Personnel reached the indoor objective.',
  route_blocked: 'East passage closed. West detour and alternate assembly area required.',
  evacuation_requested: 'Evacuation requested. Personnel hold while route coverage is checked.',
  evacuation_started: 'Personnel withdrawing. Position and trail recording continue.',
  personnel_evacuated: 'All enrolled personnel accounted for outdoors. Fleet recovery available.',
  coverage_ready: 'Measured anchors and fresh fixes verified. Evacuation may proceed.',
  coverage_unavailable: 'Coverage unavailable. Personnel hold; fleet recovery stays locked.',
  recall_rejected: 'Personnel have not completed evacuation. Positioning nodes remain on site.',
};
const nodeEvents = {
  anchor_fault_injected: 'ranging output disabled.',
  anchor_failed: 'ranging timed out. Excluded; replacement scheduled.',
  replacement_dispatched: 'dispatched to the reserve anchor site.',
  replacement_complete: 'replacement perched and calibrated.',
  coverage_dispatched: 'moving to extend evacuation coverage; remaining nodes keep tracking.',
  coverage_perched: 'perched at the new site. Verifying fresh ranging before departure.',
};
export function eventText(event) {
  if (event.code === 'objective' && printableEnglish(event.text)) return event.text;
  if (events[event.code]) return events[event.code];
  const text = String(event.text ?? '');
  const identity = text.match(/^D\d+\b/)?.[0] || 'Node';
  if (nodeEvents[event.code]) return `${identity} ${nodeEvents[event.code]}`;
  if (event.code === 'drone_state') {
    const state = text.trim().split(/\s+/).at(-1);
    return `${identity} / ${droneText[state] || 'Unknown state'}`;
  }
  return printableEnglish(text) ? text : `Event details unavailable (${printableEnglish(event.code) ? event.code : 'unknown'}).`;
}
