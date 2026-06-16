import type { Conversation, SendResult, Topic, CreateTopicBody, ResearchResult, SourceDoc, Foundation, EventOut, Curriculum, Item, Assessment, Rubric, Retention, SRSCard, AssessBody, Remediation, Anchor, AnchorGen } from './types';

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  listTopics: () => fetch('/api/topics').then(j<Topic[]>),
  startConversation: (topic_id: number, concept_id: number) =>
    fetch('/api/conversations', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ topic_id, concept_id })
    }).then(j<Conversation>),
  sendMessage: (id: number, content: string) =>
    fetch(`/api/conversations/${id}/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ content })
    }).then(j<SendResult>),
  createTopic: (body: CreateTopicBody) =>
    fetch('/api/topics', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<Topic>),
  runResearch: (topicId: number) =>
    fetch(`/api/topics/${topicId}/research`, { method: 'POST' }).then(j<ResearchResult>),
  getFoundation: (topicId: number) =>
    fetch(`/api/topics/${topicId}/foundation`).then(j<Foundation>),
  listEvents: (topicId: number) => fetch(`/api/topics/${topicId}/events`).then(j<EventOut[]>),
  listSources: (topicId: number, status?: string) =>
    fetch(`/api/topics/${topicId}/sources${status ? `?status=${status}` : ''}`).then(j<SourceDoc[]>),
  reviewSources: (topicId: number, accepted_ids: number[], pruned_ids: number[]) =>
    fetch(`/api/topics/${topicId}/sources/review`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ accepted_ids, pruned_ids })
    }).then(j<SourceDoc[]>),
  generateCurriculum: (topicId: number) =>
    fetch(`/api/topics/${topicId}/curriculum`, { method: 'POST' }).then(j<Curriculum>),
  getCurriculum: (topicId: number) =>
    fetch(`/api/topics/${topicId}/curriculum`).then(j<Curriculum>),
  exportCurriculumMd: (topicId: number) =>
    fetch(`/api/topics/${topicId}/curriculum.md`).then((r) => r.text()),
  updateItem: (itemId: number, patch: { status?: string; text?: string }) =>
    fetch(`/api/items/${itemId}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(patch)
    }).then(j<Item>),
  assess: (conceptId: number, body: AssessBody) =>
    fetch(`/api/concepts/${conceptId}/assess`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<Assessment>),
  listAssessments: (conceptId: number) =>
    fetch(`/api/concepts/${conceptId}/assessments`).then(j<Assessment[]>),
  getRubric: (conceptId: number) =>
    fetch(`/api/concepts/${conceptId}/rubric`).then(j<Rubric>),
  proposeRetention: (conceptId: number, from_assessment_id?: number) =>
    fetch(`/api/concepts/${conceptId}/retention/propose`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ from_assessment_id })
    }).then(j<Retention>),
  listRetention: (topicId: number, opts?: { status?: string; due?: boolean }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set('status', opts.status);
    if (opts?.due) q.set('due', 'true');
    const qs = q.toString();
    return fetch(`/api/topics/${topicId}/retention${qs ? `?${qs}` : ''}`).then(j<Retention>);
  },
  reviewCard: (cardId: number, status: string) =>
    fetch(`/api/retention/cards/${cardId}/review`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ status })
    }).then(j<SRSCard>),
  gradeCard: (cardId: number, result: string) =>
    fetch(`/api/retention/cards/${cardId}/grade`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ result })
    }).then(j<SRSCard>),
  remediate: (conceptId: number, from_assessment_id?: number) =>
    fetch(`/api/concepts/${conceptId}/remediate`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ from_assessment_id })
    }).then(j<Remediation>),
  generateAnchors: (topicId: number) =>
    fetch(`/api/topics/${topicId}/anchors`, { method: 'POST' }).then(j<AnchorGen>),
  listConceptAnchors: (conceptId: number) =>
    fetch(`/api/concepts/${conceptId}/anchors`).then(j<Anchor[]>),
};
