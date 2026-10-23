import { render } from 'svelte/server';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import ConfirmAction from './ConfirmAction.svelte';

const props = {
  label: 'Delete topic',
  question: 'Delete Bayesian A/B testing?',
  confirmLabel: 'Yes, delete it',
  busyLabel: 'Deleting…',
  onconfirm: () => {}
};

describe('ConfirmAction', () => {
  it('starts closed: only the action button, nothing destructive on screen', () => {
    const { body } = render(ConfirmAction, {
      props: {
        ...props,
        detail: createRawSnippet(() => ({ render: () => '<span>Notes in your vault stay there.</span>' }))
      }
    });
    expect(body).toContain('Delete topic');
    expect(body).toContain('data-confirm-trigger');
    expect(body).not.toContain('Yes, delete it');
    expect(body).not.toContain('Notes in your vault stay there.');
    expect(body).not.toContain('role="group"');
  });
});
