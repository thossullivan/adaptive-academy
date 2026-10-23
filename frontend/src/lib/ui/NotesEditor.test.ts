import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { NotebookItem } from '$lib/types';
import NotebookItems from './NotebookItems.svelte';
import NotesEditor from './NotesEditor.svelte';

describe('NotesEditor', () => {
  it('labels the box for the concept and starts saved, with Save off', () => {
    const { body } = render(NotesEditor, {
      props: { conceptId: 4, conceptName: 'Softmax', saved: 'mine', savedAt: '2026-10-22T09:00:00' }
    });
    expect(body).toMatch(/<label[^>]*>My notes on Softmax<\/label>/);
    expect(body).toContain('mine</textarea>');
    expect(body).toContain('data-state="saved"');
    expect(body).toMatch(/Saved(<!--[^>]*-->)*<span class="text-faint"> · /);
    expect(body).toMatch(/<button[^>]*disabled[^>]*>(<!---->)?\s*Save notes/);
    expect(body).toContain('aria-keyshortcuts="Control+S Meta+S"');
  });

  it('offers no Discard draft or conflict choice while nothing is unsaved', () => {
    const { body } = render(NotesEditor, { props: { conceptId: 4, conceptName: 'Softmax', saved: 'mine', savedAt: '2026-10-22T09:00:00' } });
    expect(body).not.toContain('Discard draft');
    expect(body).not.toContain('Keep my draft');
  });

  it('says there are no notes yet for a new concept', () => {
    const { body } = render(NotesEditor, { props: { conceptId: 4, conceptName: 'Softmax' } });
    expect(body).toContain('No notes yet');
  });
});

const item = (over: Partial<NotebookItem>): NotebookItem => ({
  kind: 'attempt',
  id: 1,
  created_at: '2026-10-22T09:00:00',
  source: 'tutor',
  text: 'my working',
  conversation_id: 3,
  accepted: true,
  assessment_kind: null,
  label: '',
  prompt: '',
  score: null,
  verdict: '',
  gaps: [],
  ...over
});

describe('NotebookItems', () => {
  it('shows each part, marks a rejected attempt, and links back to where it was made', () => {
    const items = [
      item({ id: 9, kind: 'explanation', source: 'teach', label: 'Teach-back', score: 0.7, gaps: ['no example'], text: 'taught' }),
      item({ id: 8, kind: 'solution', text: 'the worked answer' }),
      item({ id: 7, accepted: false, text: 'a guess' })
    ];
    const { body } = render(NotebookItems, { props: { items, topicId: 2, conceptId: 5 } });
    expect(body).toContain('My attempts');
    expect(body).toContain('Attempt, not accepted');
    // The score is shown in its level's colour (0.7 is "medium": the accent, utils levelColor).
    expect(body).toMatch(/Teach-back(<!--[^>]*-->)*, <span class="nums" data-testid="item-score" style="color: var\(--accent\);">70 of 100<\/span>/);
    expect(body).toContain('no example');
    expect(body).toContain('the worked answer');
    expect(body).toContain('href="/topics/2/teach"');
    expect(body).toContain('href="/topics/2/tutor?concept=5"');
  });

  it('says what to do when a part is empty', () => {
    const { body } = render(NotebookItems, { props: { items: [], topicId: 2, conceptId: 5 } });
    expect(body).toContain('No attempts yet.');
    expect(body).toContain('No worked solutions yet.');
    expect(body.replace(/<!--[^>]*-->/g, '')).not.toMatch(/[—!]/);
  });
});
