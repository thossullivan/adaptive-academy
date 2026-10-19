export interface Concept { id: number; name: string; is_load_bearing: boolean; has_anchor?: boolean; }
export type GraphEdgeKind = 'prerequisite' | 'related' | 'alias';
export interface GraphEdge {
  src: number;
  dst: number;
  kind: GraphEdgeKind;
  weight: number;
}
export interface GraphLink {
  source: number;
  target: number;
  kind: GraphEdgeKind;
  weight: number;
}
export interface ConceptGraph { nodes: Concept[]; edges: GraphEdge[]; }
export type GraphAncestor = [conceptId: number, depth: number];
export interface Topic { id: number; title: string; concepts: Concept[]; intent?: Intent | null; }
export interface EventOut { kind: string; detail: string; }
export interface MemoryHit {
  chunk_id: number;
  kind: string;
  heading: string;
  snippet: string;
  score: number;
  source_ref: string;
}
export interface MessageOut { role: 'user' | 'tutor'; content: string; memory?: MemoryHit[]; }
export interface Conversation {
  id: number; concept_id: number; attempt_logged: boolean;
  assistance_level: string; challenge_level: string; messages: MessageOut[];
}
export interface SendMessageOut {
  reply: string; attempt_logged: boolean;
  assistance_level: string; challenge_level: string; events: EventOut[]; memory: MemoryHit[];
}
export type SendResult = SendMessageOut;
export interface Intent { goal: string; prior_knowledge: string; time_budget: string; }
export interface SourceDoc {
  id: number; title: string; url: string; tier: number;
  summary: string; why: string; rank: number; angle: string; status: string;
}
export interface Foundation { overview: string; key_concepts: string[]; prerequisite_map: Record<string, string[]>; }
export interface ResearchResult { foundation: Foundation; sources: SourceDoc[]; events: EventOut[]; }
/** GET /api/setup — can the API make LLM calls? Never carries the key itself. */
export interface SetupStatus { llm_backend: 'anthropic' | 'agent_sdk'; llm_ready: boolean; message: string; }
export interface CreateTopicBody { title: string; goal: string; prior_knowledge?: string; time_budget?: string; }
export interface Item { id: number; text: string; type: string; status: string; position: number; is_remediation?: boolean; }
export interface Remediation { items: Item[]; events: EventOut[]; }
export interface Deliverable { id: number; kind: string; text: string; acceptance_criteria: string[]; artifact_url?: string; review_verdict?: string; }
export interface ShipResult { score: number; verdict: string; gaps: string[]; concepts: string[]; }
export interface Sidebar { id: number; kind: string; title: string; body: string; position: number; }
export interface Phase {
  id: number; title: string; position: number; est_hours: string; flags: string[];
  items: Item[]; deliverable: Deliverable | null;
}
export interface TrackInfo { id: number; title: string; overview: string; }
export interface Curriculum {
  track: TrackInfo; phases: Phase[]; sidebars: Sidebar[]; concepts: Concept[]; events: EventOut[];
}
export interface Assessment {
  id: number; kind: string; prompt: string; response: string; verdict: string;
  score: number; gaps: string[]; confidence_predicted: number | null;
  confidence_actual: number | null; delta: number | null; estimate_level: string | null;
}
export interface Rubric {
  id: number; concept_id: number; criteria: string[]; must_include: string[];
  strong_signs: string[]; weak_signs: string[]; reviewed_by_user: boolean;
}
export interface SRSCard {
  id: number; concept_id: number; front: string; back: string; status: string;
  interval: number; reps: number; last_result: string;
}
export interface RecallPromptItem { id: number; concept_id: number; prompt: string; status: string; }
export interface Retention { cards: SRSCard[]; prompts: RecallPromptItem[]; }
export interface AssessBody {
  kind: string; response?: string; confidence_predicted?: number | null;
  baseline_id?: number | null; item_id?: number | null; anchor_id?: number | null;
}
export interface Anchor { id: number; source_doc_id: number; concept_id: number | null; question: string; reference_answer: string; key_points: string[]; }
export interface AnchorGen { anchors: Anchor[]; events: EventOut[]; }
export interface StoryFacts {
  topic_title: string; goal: string; span_days: number;
  items_done: number; items_total: number; progress_pct: number;
  phases_completed: number; phases_total: number; shipped: string[];
  concepts_solid: string[]; concepts_developing: string[]; concepts_shaky: string[];
  load_bearing_shaky: string[]; assessments_count: number; mean_score: number | null;
  improvements: string[]; calibration_note: string;
}
export interface Story {
  headline: string; narrative: string[]; highlights: string[];
  facts: StoryFacts; events: EventOut[];
}
export interface DecayItem { prompt_id: number; concept_id: number; concept_name: string; prompt: string; last_result: string; }
export interface DecayDue { items: DecayItem[]; }
export interface DecayGrade {
  recall_score: number; baseline_score: number | null; decay_delta: number | null;
  held: boolean; verdict: string; gaps: string[]; estimate_level: string;
}
export interface Challenge { problem: string; }
export interface Consolidation { canonical: string; feedback: string; score: number; }
export interface TeachResult { score: number; feedback: string; strengths: string[]; gaps: string[]; }

export interface VaultStatus {
  configured: boolean;
  path: string;
  exists: boolean;
  is_dir: boolean;
  note_count: number;
}
export interface VaultIngestResult {
  count: number;
  titles: string[];
}
export interface VaultExportResult {
  written: string[];
}
export interface VaultExportAllResult {
  topics: number;
  written: string[];
}
export interface MemorySearchResult { hits: MemoryHit[]; }
export interface MemoryReindexBody {
  topic_id?: number;
  vault_path?: string;
  kinds?: string[];
}
export interface MemoryReindexResult {
  indexed: number;
  skipped: number;
  removed: number;
  truncated: boolean;
  ms: number;
}
export interface MemoryStats {
  by_kind: Record<string, number>;
  last_indexed_at: string | null;
  retriever: string;
}

export interface WindState {
  topic_id: number;
  topic_title: string;
  value: number;
  state: string;
  last_sailed: string | null;
  days_since: number | null;
  progress: number;
}
export interface ComebackMove {
  kind: string;
  label: string;
  href: string;
  minutes: number;
}
export interface Comeback {
  move: ComebackMove | null;
}

export interface Program {
  id: number; title: string; goal_statement: string; status: string; milestone_count: number;
}
export interface LinkInfo {
  id: number; status: string; proposed_title: string; why: string;
  sources: string[]; topic_id: number | null; added_by: string;
}
export interface MilestoneInfo {
  id: number; title: string; success_criteria: string; order_index: number;
  gate_status: string; depends_on: number[]; override_reason: string; links: LinkInfo[];
  archived: boolean;
}
export interface ProgramDetail {
  program: Program; milestones: MilestoneInfo[];
  revision_suggested: boolean; has_open_revision: boolean;
}
export interface MapChange {
  id: number; kind: string; payload: Record<string, unknown>;
  why: string; source_urls: string[]; status: string;
}
export interface MapRevisionInfo { id: number; map_health: string; changes: MapChange[]; }
export interface ConceptEvidence {
  concept_id: number; name: string; delayed_ok: boolean; artifact_ok: boolean; verdict: string;
}
export interface GateReport {
  milestone_id: number; verdict: string; reason: string; concepts: ConceptEvidence[];
}
export interface ProgramContext {
  program_id: number; program_title: string; milestone_id: number;
  milestone_title: string; gate_status: string; unverified: string[];
  revision_suggested: boolean;
}
export interface CreateProgramBody {
  title: string; goal_statement?: string; target_depth?: string; prior_knowledge?: string;
  weekly_time_budget?: string; horizon?: string; focus_area?: string;
}

export interface ScoutEvidence {
  kind: string;
  id?: number;
  ref?: string;
  name?: string;
}
export interface TopicSuggestion {
  id: number;
  program_id: number;
  title: string;
  rationale: string;
  candidate_kind: string;
  evidence: ScoutEvidence[];
  score: number;
  status: string;
  created_at: string;
  decided_at: string | null;
}
export interface ScoutResult {
  suggestions: TopicSuggestion[];
  candidates: Record<string, number>;
  truncated: boolean;
}
export interface ScoutSuggestionGroup {
  kind: string;
  suggestions: TopicSuggestion[];
}

export type RoleplayTurnRow = { role: 'user' | 'persona'; content: string };
export type ScorecardRow = { concept_id: number; concept: string; score: number; verdict: string; gaps: string[] };
export type RoleplaySession = {
  session_id: number;
  program_id: number;
  status: 'briefing' | 'active' | 'ended' | 'graded';
  brief_public: { persona?: string; situation?: string };
  turns: RoleplayTurnRow[];
  outcome?: { result: string; summary: string } | null;
  scorecard?: ScorecardRow[] | null;
};
export type RoleplayTurnResult = { reply: string; status: RoleplaySession['status'] };

export type PaperQuestion = { index: number; axis: string; prompt: string };
export type PaperAnswerRow = { question_index: number; content: string };
export type PaperProbe = {
  probe_id: number;
  program_id: number;
  milestone_id: number;
  status: 'drafting' | 'answering' | 'graded';
  paper: { title: string; url: string; source: string };
  questions: PaperQuestion[];
  answers: PaperAnswerRow[];
  outcome?: { result: string; summary: string } | null;
  scorecard?: ScorecardRow[] | null;
};
