import type { UsageBudget, UsageTotals } from './types';

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
  scout: 'Scout'
};

/** Display name for a feature label from the API; null = a call made outside a request. */
export function featureLabel(feature: string | null): string {
  if (feature == null) return 'Background / other';
  const known = FEATURE_NAMES[feature];
  if (known) return known;
  const words = feature.replaceAll('_', ' ').replaceAll('-', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Share of today's limit already spent, clamped to [0, 1]; null when no limit is set. */
export function budgetFraction(b: UsageBudget): number | null {
  if (b.limit_usd == null) return null;
  if (b.limit_usd <= 0) return 1;
  return Math.min(Math.max(b.spent_today_usd / b.limit_usd, 0), 1);
}
