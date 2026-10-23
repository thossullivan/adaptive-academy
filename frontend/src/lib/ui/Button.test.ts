import { createRawSnippet } from 'svelte';
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Button from './Button.svelte';
import Input from './Input.svelte';
import Select from './Select.svelte';
import Textarea from './Textarea.svelte';

const children = createRawSnippet(() => ({ render: () => '<span>Go</span>' }));
const classOf = (body: string) => body.match(/<button[^>]*class="([^"]*)"/)?.[1] ?? '';

describe('disabled look', () => {
  it('a disabled primary turns flat grey: surface-3, faint text, no shadow (not a faded brown button)', () => {
    const cls = classOf(render(Button, { props: { children, disabled: true } }).body);
    expect(cls).toContain('disabled:bg-surface-3');
    expect(cls).toContain('disabled:text-faint');
    expect(cls).toContain('disabled:shadow-none');
    expect(cls).not.toMatch(/disabled:opacity/);
  });

  it('form controls switch off the same way: surface-3, faint text, no opacity, boundary kept', () => {
    const options = createRawSnippet(() => ({ render: () => '<option>a</option>' }));
    const bodies = [
      render(Input, { props: { disabled: true, 'aria-label': 'x' } }).body,
      render(Textarea, { props: { disabled: true, 'aria-label': 'x' } }).body,
      render(Select, { props: { disabled: true, 'aria-label': 'x', children: options } }).body
    ];
    for (const body of bodies) {
      const cls = body.match(/<(?:input|textarea|select)[^>]*class="([^"]*)"/)?.[1] ?? '';
      expect(cls).toContain('disabled:bg-surface-3');
      expect(cls).toContain('disabled:text-faint');
      expect(cls).toContain('border-control-border'); // still a 3:1 edge (WCAG 1.4.11)
      expect(cls).not.toMatch(/disabled:opacity/);
    }
  });

  for (const variant of ['outline', 'ghost', 'danger'] as const) {
    it(`a disabled ${variant} button uses faint text, not opacity`, () => {
      const cls = classOf(render(Button, { props: { children, disabled: true, variant } }).body);
      expect(cls).toContain('disabled:text-faint');
      expect(cls).not.toMatch(/disabled:opacity/);
    });
  }
});
