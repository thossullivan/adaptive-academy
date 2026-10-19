import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Merge Tailwind classes with conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Map a knowledge-estimate level to a 0..1 fill fraction. */
export const LEVEL_FILL: Record<string, number> = {
  high: 1,
  medium: 0.6,
  low: 0.3,
  unknown: 0.12
};

/** Human label for a knowledge level. */
export const LEVEL_LABEL: Record<string, string> = {
  high: 'solid',
  medium: 'developing',
  low: 'shaky',
  unknown: 'unmeasured'
};

/** Token color for a knowledge level (CSS var reference). */
export function levelColor(level: string | null | undefined): string {
  switch (level) {
    case 'high':
      return 'var(--success)';
    case 'medium':
      return 'var(--accent)';
    case 'low':
      return 'var(--danger)';
    default:
      return 'var(--faint)';
  }
}

/** 'smooth' scrolling, or an instant jump when the user asks for reduced motion. */
export function scrollBehavior(): ScrollBehavior {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ? 'auto'
    : 'smooth';
}

/** Clamp a number into [min, max]. */
export function clamp(n: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, n));
}

/** Format a 0..1 score as a percentage string. */
export function pct(n: number | null | undefined): string {
  if (n == null) return '—';
  return `${Math.round(n * 100)}%`;
}
