// Display measured segments only. Never invent a detour or move a solved fix.
function crosses(a, b, [x, y, w, h]) {
  let low = 0, high = 1;
  for (const [origin, delta, minimum, maximum] of [[a[0], b[0] - a[0], x, x + w], [a[1], b[1] - a[1], y, y + h]]) {
    if (Math.abs(delta) < 1e-10) {
      if (origin < minimum || origin > maximum) return false;
    } else {
      const t0 = (minimum - origin) / delta, t1 = (maximum - origin) / delta;
      low = Math.max(low, Math.min(t0, t1));
      high = Math.min(high, Math.max(t0, t1));
      if (low > high) return false;
    }
  }
  return true;
}

export function trailSegments(trail, walls) {
  const points = [];
  for (let i = 1; i < trail.length; i++) {
    const a = trail[i - 1], b = trail[i];
    if (a && b && !walls.some(wall => crosses(a, b, wall))) points.push(a, b);
  }
  return points;
}
