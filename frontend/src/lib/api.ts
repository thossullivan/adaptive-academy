import type { Conversation, SendResult, Topic, CreateTopicBody, ResearchResult, SourceDoc, Foundation, EventOut, Curriculum, Item, Assessment, Rubric, Retention, SRSCard, AssessBody, Remediation, Anchor, AnchorGen, Story, DecayDue, DecayGrade, Challenge, Consolidation, TeachResult, ShipResult, VaultStatus, VaultIngestResult, VaultExportResult, VaultExportAllResult, WindState, Comeback, Program, ProgramDetail, CreateProgramBody, GateReport, MilestoneInfo, ProgramContext, MapRevisionInfo, RoleplaySession, RoleplayTurnResult, PaperProbe } from './types';

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  listTopics: () => fetch('/api/topics').then(j<Topic[]>),
  getTopic: (id: number) => fetch(`/api/topics/${id}`).then(j<Topic>),
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
  makeStory: (topicId: number) =>
    fetch(`/api/topics/${topicId}/story`, { method: 'POST' }).then(j<Story>),
  listDecay: (topicId: number) => fetch(`/api/topics/${topicId}/decay`).then(j<DecayDue>),
  gradeDecay: (promptId: number, response: string) =>
    fetch(`/api/decay/${promptId}/grade`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ response })
    }).then(j<DecayGrade>),
  generateChallenge: (conceptId: number) =>
    fetch(`/api/concepts/${conceptId}/productive_failure/generate`, { method: 'POST' }).then(j<Challenge>),
  consolidate: (conceptId: number, problem: string, attempt: string) =>
    fetch(`/api/concepts/${conceptId}/productive_failure/consolidate`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ problem, attempt })
    }).then(j<Consolidation>),
  gradeTeaching: (conceptId: number, explanation: string) =>
    fetch(`/api/concepts/${conceptId}/teach`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ explanation })
    }).then(j<TeachResult>),
  shipDeliverable: (deliverableId: number, artifact_url: string, content: string) =>
    fetch(`/api/deliverables/${deliverableId}/ship`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ artifact_url, content })
    }).then(j<ShipResult>),

  vaultStatus: (vaultPath: string) =>
    fetch(`/api/vault/status?vault_path=${encodeURIComponent(vaultPath)}`).then(j<VaultStatus>),
  vaultIngest: (topicId: number, vault_path: string, subfolder = '') =>
    fetch(`/api/topics/${topicId}/vault/ingest`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ vault_path, subfolder })
    }).then(j<VaultIngestResult>),
  vaultExport: (topicId: number, vault_path: string) =>
    fetch(`/api/topics/${topicId}/vault/export`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ vault_path })
    }).then(j<VaultExportResult>),
  vaultExportAll: (vault_path: string) =>
    fetch('/api/vault/export-all', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ vault_path })
    }).then(j<VaultExportAllResult>),
  getFleet: () => fetch('/api/fleet').then(j<WindState[]>),
  getWind: (topicId: number) => fetch(`/api/topics/${topicId}/wind`).then(j<WindState>),
  getComeback: (topicId: number) => fetch(`/api/topics/${topicId}/comeback`).then(j<Comeback>),

  listPrograms: () => fetch('/api/programs').then(j<Program[]>),
  createProgram: (body: CreateProgramBody) =>
    fetch('/api/programs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<Program>),
  getProgram: (id: number) => fetch(`/api/programs/${id}`).then(j<ProgramDetail>),
  programResearch: (id: number) =>
    fetch(`/api/programs/${id}/research`, { method: 'POST' }).then(j<ProgramDetail>),
  acceptProgram: (id: number, accepted_link_ids: number[], pruned_link_ids: number[]) =>
    fetch(`/api/programs/${id}/accept`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ accepted_link_ids, pruned_link_ids })
    }).then(j<ProgramDetail>),
  startLink: (pid: number, linkId: number) =>
    fetch(`/api/programs/${pid}/links/${linkId}/start`, { method: 'POST' }).then(j<{ topic_id: number }>),
  milestoneGate: (pid: number, mid: number) =>
    fetch(`/api/programs/${pid}/milestones/${mid}/gate`).then(j<GateReport>),
  overrideGate: (pid: number, mid: number, reason: string) =>
    fetch(`/api/programs/${pid}/milestones/${mid}/override`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ reason })
    }).then(j<MilestoneInfo>),
  updateMilestone: (pid: number, mid: number, body: Partial<Pick<MilestoneInfo, 'title' | 'success_criteria' | 'order_index' | 'depends_on'>>) =>
    fetch(`/api/programs/${pid}/milestones/${mid}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<MilestoneInfo>),
  programContext: (topicId: number) =>
    fetch(`/api/topics/${topicId}/program-context`).then((r) =>
      r.status === 404 ? null : j<ProgramContext>(r)
    ),
  reviseMap: (id: number) =>
    fetch(`/api/programs/${id}/revise`, { method: 'POST' }).then(j<MapRevisionInfo>),
  getOpenRevision: (id: number) =>
    fetch(`/api/programs/${id}/revision`).then((r) =>
      r.status === 404 ? null : j<MapRevisionInfo>(r)
    ),
  acceptChange: (pid: number, changeId: number) =>
    fetch(`/api/programs/${pid}/changes/${changeId}/accept`, { method: 'POST' }).then(j<ProgramDetail>),
  rejectChange: (pid: number, changeId: number) =>
    fetch(`/api/programs/${pid}/changes/${changeId}/reject`, { method: 'POST' }).then(j<ProgramDetail>),

  startRoleplay: (programId: number, milestoneId: number) =>
    fetch(`/api/programs/${programId}/milestones/${milestoneId}/roleplay`, { method: 'POST' })
      .then(j<RoleplaySession>),
  getRoleplay: (sid: number) => fetch(`/api/roleplay/${sid}`).then(j<RoleplaySession>),
  sendRoleplayTurn: (sid: number, content: string) =>
    fetch(`/api/roleplay/${sid}/turns`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ content })
    }).then(j<RoleplayTurnResult>),
  endRoleplay: (sid: number) =>
    fetch(`/api/roleplay/${sid}/end`, { method: 'POST' }).then(j<RoleplaySession>),

  startPaperProbe: (
    programId: number,
    milestoneId: number,
    body: { url?: string; pasted_text?: string; title?: string }
  ) =>
    fetch(`/api/programs/${programId}/milestones/${milestoneId}/paper-probe`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<PaperProbe>),
  getPaperProbe: (pid: number) => fetch(`/api/paper-probe/${pid}`).then(j<PaperProbe>),
  answerPaperProbe: (pid: number, question_index: number, content: string) =>
    fetch(`/api/paper-probe/${pid}/answers`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question_index, content })
    }).then(j<{ status: string }>),
  submitPaperProbe: (pid: number) =>
    fetch(`/api/paper-probe/${pid}/submit`, { method: 'POST' }).then(j<PaperProbe>)
};

/** Derive a per-concept knowledge level from its assessment history (latest estimate). */
export async function conceptLevels(conceptIds: number[]): Promise<Record<number, string>> {
  const lists = await Promise.all(
    conceptIds.map((id) => api.listAssessments(id).catch(() => [] as Assessment[]))
  );
  const out: Record<number, string> = {};
  conceptIds.forEach((id, i) => {
    // listAssessments returns newest-first, so the latest estimate is index 0.
    const latest = lists[i][0];
    out[id] = latest?.estimate_level ?? 'unknown';
  });
  return out;
}
