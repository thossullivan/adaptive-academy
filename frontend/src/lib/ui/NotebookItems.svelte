<script lang="ts">
  import { SOURCE_LABEL, formatWhen, itemHeading, itemHeadingParts, notebookSections, scoreLevel, sourceHref } from '$lib/notebook';
  import type { NotebookItem } from '$lib/types';
  import { levelColor } from '$lib/utils';
  import Badge from './Badge.svelte';
  import Markdown from './Markdown.svelte';

  // A concept's work, by part, newest first: attempts, graded explanations, worked solutions.
  // Each item says when and where it was made, and links back there.
  let {
    items,
    topicId,
    conceptId
  }: {
    items: NotebookItem[];
    topicId: number;
    conceptId: number;
  } = $props();

  const uid = $props.id();
  const parts = $derived.by(() => {
    const s = notebookSections(items);
    return [
      { key: 'attempts', title: 'My attempts', empty: 'No attempts yet. On the Tutor page, write your attempt and press Submit attempt.', items: s.attempts },
      { key: 'explanations', title: 'My explanations', empty: 'No graded explanations yet. Explain the concept on Assess or Teach.', items: s.explanations },
      { key: 'solutions', title: 'Worked solutions', empty: 'No worked solutions yet. The tutor shows one after an accepted attempt.', items: s.solutions }
    ];
  });
</script>

{#each parts as part (part.key)}
  <section class="flex flex-col gap-2" aria-labelledby="{uid}-{part.key}" data-testid="notebook-{part.key}">
    <h3 id="{uid}-{part.key}" class="eyebrow">{part.title} · <span class="nums">{part.items.length}</span></h3>
    {#if !part.items.length}
      <p class="text-sm text-muted">{part.empty}</p>
    {:else}
      <ul class="flex flex-col gap-2">
        {#each part.items as item (`${item.kind}-${item.id}`)}
          <li class="min-w-0 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              {#if item.kind === 'attempt' && !item.accepted}
                <Badge tone="warn">{itemHeading(item)}</Badge>
              {:else}
                {@const head = itemHeadingParts(item)}
                <!-- The score in its level's colour, as on the dashboard (utils levelColor). -->
                <span class="font-medium text-fg"
                  >{head.title}{#if head.score && item.score != null},
                    <span class="nums" style:color={levelColor(scoreLevel(item.score))} data-testid="item-score">{head.score}</span
                    >{/if}</span
                >
              {/if}
              <time datetime={item.created_at} class="text-muted">{formatWhen(item.created_at)}</time>
              <span class="text-muted">
                · made in <a class="text-accent underline underline-offset-2" href={sourceHref(item, topicId, conceptId)}>{SOURCE_LABEL[item.source]}</a>
              </span>
            </div>
            {#if item.prompt}
              <!-- Prompts carry markdown emphasis ("Explain *why* …"): formatted, not shown raw. -->
              <p class="md-wrap mt-1.5 text-xs text-muted [overflow-wrap:anywhere]">Prompt: <Markdown text={item.prompt} /></p>
            {/if}
            <!-- A worked solution is the tutor's markdown; attempts and explanations are the
                 learner's own words, shown exactly as typed. -->
            <!-- A div, not a p: a worked solution can hold a list. -->
            <div class="md-wrap mt-1.5 text-sm leading-relaxed text-fg-dim [overflow-wrap:anywhere]">
              {#if !item.text}(empty){:else if item.kind === 'solution'}<Markdown text={item.text} pre />{:else}<span
                  class="whitespace-pre-wrap">{item.text}</span
                >{/if}
            </div>
            {#if item.verdict}
              <p class="mt-1.5 text-xs text-muted [overflow-wrap:anywhere]">{item.verdict}</p>
            {/if}
            {#if item.gaps.length}
              <p class="mt-1 text-xs text-muted [overflow-wrap:anywhere]"><span class="text-fg-dim">Gaps:</span> {item.gaps.join('; ')}</p>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
{/each}
