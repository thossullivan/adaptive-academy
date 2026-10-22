import { describe, expect, it, vi } from 'vitest';
import { api } from './api';
import type { QualityCalls, UsageBudget, UsageTotals } from './types';
import {
  budgetFraction,
  cacheShareLabel,
  callDestination,
  costLabel,
  featureLabel,
  formatTokens,
  formatUnitCost,
  formatUsd,
  perCallLabel,
  perGradeLabel,
  problemParts,
  problemsLabel,
  shareLabel,
  totalTokens
} from './usage';

const zero: UsageTotals = {
  calls: 0,
  cost_usd: 0,
  api_cost_usd: 0,
  unpriced_calls: 0,
  input_tokens: 0,
  output_tokens: 0,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  web_search_requests: 0
};

describe('formatUsd', () => {
  it('shows cents, a floor for tiny spend, and grouping for large sums', () => {
    expect(formatUsd(0)).toBe('$0.00');
    expect(formatUsd(0.004)).toBe('<$0.01');
    expect(formatUsd(0.016)).toBe('$0.02');
    expect(formatUsd(12.5)).toBe('$12.50');
    expect(formatUsd(1234.567)).toBe('$1,234.57');
  });
});

describe('formatTokens', () => {
  it('abbreviates thousands and millions', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(950)).toBe('950');
    expect(formatTokens(12_345)).toBe('12.3k');
    expect(formatTokens(2_500_000)).toBe('2.5M');
  });
});

describe('totalTokens', () => {
  it('sums input, output, and both cache directions', () => {
    expect(
      totalTokens({
        ...zero,
        input_tokens: 1,
        output_tokens: 2,
        cache_creation_input_tokens: 3,
        cache_read_input_tokens: 4
      })
    ).toBe(10);
  });
});

describe('costLabel', () => {
  it('says "price unknown" only when no call in the group had a price', () => {
    expect(costLabel({ ...zero, calls: 2, unpriced_calls: 2 })).toBe('price unknown');
    expect(costLabel({ ...zero, calls: 3, unpriced_calls: 1, cost_usd: 0.5 })).toBe('$0.50');
    expect(costLabel(zero)).toBe('$0.00');
  });
});

describe('featureLabel', () => {
  it('names known features and humanises the rest', () => {
    expect(featureLabel('tutor')).toBe('Tutor');
    expect(featureLabel('paper_probe')).toBe('Paper probe');
    expect(featureLabel('productive_failure')).toBe('Productive failure');
    expect(featureLabel('some_new_thing')).toBe('Some new thing');
    expect(featureLabel(null)).toBe('Background / other');
  });
});

describe('budgetFraction', () => {
  const b = (limit: number | null, spent: number): UsageBudget => ({
    limit_usd: limit,
    spent_today_usd: spent,
    remaining_usd: limit == null ? null : Math.max(limit - spent, 0),
    exceeded: limit != null && spent >= limit
  });

  it('is null without a limit and clamps to [0, 1]', () => {
    expect(budgetFraction(b(null, 3))).toBeNull();
    expect(budgetFraction(b(4, 1))).toBe(0.25);
    expect(budgetFraction(b(1, 5))).toBe(1);
    expect(budgetFraction(b(0, 0))).toBe(1);
  });
});

describe('cacheShareLabel', () => {
  it('floors to a whole percent, marks tiny shares, and is null when unknown', () => {
    expect(cacheShareLabel(0.6429)).toBe('64% cached');
    expect(cacheShareLabel(0.6499)).toBe('64% cached');
    expect(cacheShareLabel(0.29)).toBe('29% cached'); // not 28: 0.29 * 100 is 28.999…
    expect(cacheShareLabel(0.995)).toBe('99% cached'); // never "100%" unless it all was
    expect(cacheShareLabel(0)).toBe('0% cached');
    expect(cacheShareLabel(1)).toBe('100% cached');
    expect(cacheShareLabel(0.001)).toBe('<1% cached');
    expect(cacheShareLabel(0.009)).toBe('<1% cached');
    expect(cacheShareLabel(null)).toBeNull();
    expect(cacheShareLabel(undefined)).toBeNull();
  });
});

describe('api.getUsage', () => {
  it('GETs /api/usage', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ backend: 'anthropic' }), { status: 200 })
    );
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.getUsage();
    expect(fetchMock).toHaveBeenCalledWith('/api/usage');
    expect(out.backend).toBe('anthropic');
    vi.unstubAllGlobals();
  });
});

const calls = (over: Partial<QualityCalls> = {}): QualityCalls => ({
  calls: 0,
  cost_usd: 0,
  unpriced_calls: 0,
  cost_per_call_usd: null,
  recorded_calls: 0,
  refusals: 0,
  empty_replies: 0,
  cut_offs: 0,
  invalid_outputs: 0,
  ...over
});

describe('formatUnitCost', () => {
  it('keeps small per-call costs readable instead of "<$0.01"', () => {
    expect(formatUnitCost(0)).toBe('$0.00');
    expect(formatUnitCost(0.0495)).toBe('$0.0495');
    expect(formatUnitCost(0.0003)).toBe('$0.0003');
    expect(formatUnitCost(0.05)).toBe('$0.05');
    expect(formatUnitCost(0.012)).toBe('$0.012');
    expect(formatUnitCost(0.00004)).toBe('<$0.0001');
    expect(formatUnitCost(0.284)).toBe('$0.28');
    expect(formatUnitCost(1.5)).toBe('$1.50');
  });
});

describe('perCallLabel', () => {
  it('says why there is no figure', () => {
    expect(perCallLabel(calls())).toBe('no calls');
    expect(perCallLabel(calls({ calls: 2, unpriced_calls: 2 }))).toBe('price unknown');
    expect(perCallLabel(calls({ calls: 2, cost_per_call_usd: 0.012 }))).toBe('$0.012');
  });
});

describe('shareLabel', () => {
  it('rounds to a whole percent, marks tiny shares, and is null without a base', () => {
    expect(shareLabel(null)).toBeNull();
    expect(shareLabel(0)).toBe('0%');
    expect(shareLabel(0.004)).toBe('<1%');
    expect(shareLabel(0.2)).toBe('20%');
    expect(shareLabel(2 / 3)).toBe('67%');
    expect(shareLabel(0.996)).toBe('99%'); // never "100%" unless it all was
    expect(shareLabel(1)).toBe('100%');
  });
});

describe('problemParts', () => {
  it('lists each problem with its share of the calls that recorded an outcome', () => {
    expect(problemParts(calls({ calls: 3 }))).toEqual([]);
    expect(
      problemParts(calls({ calls: 10, recorded_calls: 8, refusals: 1, invalid_outputs: 2, cut_offs: 1 }))
    ).toEqual(['1 refused (13%)', '1 cut off (13%)', '2 wrong format (25%)']);
    expect(problemParts(calls({ calls: 1, recorded_calls: 1, empty_replies: 1 }))).toEqual([
      '1 empty (100%)'
    ]);
  });
});

describe('problemsLabel', () => {
  it('says "not recorded" when no call has an outcome, and "none" when all went fine', () => {
    expect(problemsLabel(calls())).toBe('no calls');
    expect(problemsLabel(calls({ calls: 4 }))).toBe('not recorded');
    expect(problemsLabel(calls({ calls: 4, recorded_calls: 4 }))).toBe('none');
    expect(problemsLabel(calls({ calls: 4, recorded_calls: 4, refusals: 1 }))).toBe('1 refused (25%)');
  });
});

describe('perGradeLabel', () => {
  it('shows two decimals, or null without a first attempt', () => {
    expect(perGradeLabel(null)).toBeNull();
    expect(perGradeLabel(0)).toBe('0.00');
    expect(perGradeLabel(2 / 3)).toBe('0.67');
  });
});

describe('callDestination', () => {
  it('names where each backend sends the calls', () => {
    expect(callDestination('anthropic')).toBe('Each model call itself is still sent to Anthropic.');
    expect(callDestination('openrouter')).toBe(
      "Each model call itself is still sent through OpenRouter to the model's provider."
    );
    expect(callDestination('agent_sdk')).toBe(
      'Each model call itself is still sent to Anthropic, through your Claude subscription.'
    );
  });
});

describe('api.getUsageQuality', () => {
  it('GETs /api/usage/quality', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ grading_features: ['assess'], windows: {} }), { status: 200 })
    );
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.getUsageQuality();
    expect(fetchMock).toHaveBeenCalledWith('/api/usage/quality');
    expect(out.grading_features).toEqual(['assess']);
    vi.unstubAllGlobals();
  });
});
