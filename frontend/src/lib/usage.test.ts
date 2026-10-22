import { describe, expect, it, vi } from 'vitest';
import { api } from './api';
import type { UsageBudget, UsageTotals } from './types';
import {
  budgetFraction,
  cacheShareLabel,
  costLabel,
  featureLabel,
  formatTokens,
  formatUsd,
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
  it('rounds to a whole percent, floors tiny shares, and is null when unknown', () => {
    expect(cacheShareLabel(0.6429)).toBe('64% cached');
    expect(cacheShareLabel(0)).toBe('0% cached');
    expect(cacheShareLabel(1)).toBe('100% cached');
    expect(cacheShareLabel(0.001)).toBe('<1% cached');
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
