/** Whole-number tick positions for an axis indexed 0..n-1 (one per probe).
 *
 * Few points get one tick each; many are thinned to a whole-number step so labels never
 * crowd. The last index is always included so the axis ends on the latest probe. Passing
 * `ticks={n}` to the chart instead lets d3 pick "nice" values, which can be fractional
 * (1.5, 2.5) for small n. */
export function indexTicks(n: number, maxTicks = 8): number[] {
  if (n <= 0) return [];
  const max = Math.max(1, Math.floor(maxTicks));
  if (n <= max) return Array.from({ length: n }, (_, i) => i);
  if (max === 1) return [n - 1];
  // Step chosen so first..last fits in `max` ticks including the forced last one.
  const step = Math.ceil((n - 1) / (max - 1));
  const ticks: number[] = [];
  for (let i = 0; i < n - 1; i += step) ticks.push(i);
  // Drop a penultimate tick that would crowd the final one.
  if (ticks.length && n - 1 - ticks[ticks.length - 1] < step / 2) ticks.pop();
  ticks.push(n - 1);
  return ticks.slice(-max);
}
