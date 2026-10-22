import type { LlmBackend, QualityCalls, UsageBudget, UsageTotals } from './types';

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

/** Dollars at cent precision; spend above zero but under a cent reads "<$0.01", not "$0.00". */
export function formatUsd(n: number): string {
  if (n > 0 && n < 0.005) return '<$0.01';
  return usd.format(n);
}

/** Compact token counts: 950, 12.3k, 2.5M. */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
}

export function totalTokens(t: UsageTotals): number {
  return t.input_tokens + t.output_tokens + t.cache_creation_input_tokens + t.cache_read_input_tokens;
}

/** "64% cached": the share of input tokens read from the prompt cache; null when unknown.
 * Floored, so "100% cached" means all of it and any read at all shows at least "<1%". */
export function cacheShareLabel(share: number | null | undefined): string | null {
  if (share == null) return null;
  if (share > 0 && share < 0.01) return '<1% cached';
  // The epsilon absorbs float error (0.29 * 100 is 28.999…), far below a real 1% step.
  return `${Math.floor(share * 100 + 1e-9)}% cached`;
}

/** A group's cost — or "price unknown" when none of its calls had a known model price. */
export function costLabel(t: UsageTotals): string {
  if (t.calls > 0 && t.unpriced_calls === t.calls) return 'price unknown';
  return formatUsd(t.cost_usd);
}

const FEATURE_NAMES: Record<string, string> = {
  tutor: 'Tutor',
  research: 'Research',
  curriculum: 'Curriculum',
  assess: 'Assess',
  remediate: 'Remediate',
  anchors: 'Anchors',
  roleplay: 'Roleplay',
  paper_probe: 'Paper probe',
  revision: 'Map revision',
  scout: 'Scout',
  decay: 'Recall check',
  deliverables: 'Artifact review'
};

/** Display name for a feature label from the API; null = a call made outside a request. */
export function featureLabel(feature: string | null): string {
  if (feature == null) return 'Background / other';
  const known = FEATURE_NAMES[feature];
  if (known) return known;
  const words = feature.replaceAll('_', ' ').replaceAll('-', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Where a backend sends each model call, for the page's privacy note. */
export function callDestination(backend: LlmBackend): string {
  if (backend === 'openrouter') {
    return "Each model call itself is still sent through OpenRouter to the model's provider.";
  }
  if (backend === 'agent_sdk') {
    return 'Each model call itself is still sent to Anthropic, through your Claude subscription.';
  }
  return 'Each model call itself is still sent to Anthropic.';
}

// --- The quality scorecard (GET /api/usage/quality) ---------------------------------------

/** A per-call or per-grade cost: cents from $0.10 up, else up to four decimals, so a
 * $0.003 call doesn't read as "<$0.01". */
export function formatUnitCost(n: number): string {
  if (n <= 0) return '$0.00';
  if (n < 0.0001) return '<$0.0001';
  if (n >= 0.1) return formatUsd(n);
  const [whole, decimals] = n.toFixed(4).split('.');
  return `$${whole}.${decimals.replace(/0+$/, '').padEnd(2, '0')}`;
}

/** Cost per call, or why there is none. */
export function perCallLabel(row: QualityCalls): string {
  if (row.calls === 0) return 'no calls';
  if (row.cost_per_call_usd == null) return 'price unknown';
  return formatUnitCost(row.cost_per_call_usd);
}

/** A 0..1 share as a whole percent: "<1%" for any small share, never "100%" unless it all
 * was. Null when there was nothing to take a share of. */
export function shareLabel(share: number | null | undefined): string | null {
  if (share == null) return null;
  if (share > 0 && share < 0.005) return '<1%';
  const pct = Math.round(share * 100);
  return `${share < 1 ? Math.min(pct, 99) : pct}%`;
}

/** The problems among a group's calls, each with its share of the calls that recorded an
 * outcome: "1 refused (13%)". Empty when there were none. */
export function problemParts(row: QualityCalls): string[] {
  const parts: [number, string][] = [
    [row.refusals, 'refused'],
    [row.empty_replies, 'empty'],
    [row.cut_offs, 'cut off'],
    [row.invalid_outputs, 'wrong format']
  ];
  return parts
    .filter(([n]) => n > 0)
    .map(([n, what]) => `${n} ${what} (${shareLabel(n / row.recorded_calls)})`);
}

export function problemsLabel(row: QualityCalls): string {
  if (row.calls === 0) return 'no calls';
  if (row.recorded_calls === 0) return 'not recorded';
  const parts = problemParts(row);
  return parts.length ? parts.join(', ') : 'none';
}

/** Regenerations per grade, two decimals; null with no grade checked. */
export function perGradeLabel(ratio: number | null | undefined): string | null {
  return ratio == null ? null : ratio.toFixed(2);
}

/** Share of today's limit already spent, clamped to [0, 1]; null when no limit is set. */
export function budgetFraction(b: UsageBudget): number | null {
  if (b.limit_usd == null) return null;
  if (b.limit_usd <= 0) return 1;
  return Math.min(Math.max(b.spent_today_usd / b.limit_usd, 0), 1);
}
