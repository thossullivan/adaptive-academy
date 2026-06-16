export interface Concept { id: number; name: string; is_load_bearing: boolean; }
export interface Topic { id: number; title: string; concepts: Concept[]; }
export interface EventOut { kind: string; detail: string; }
export interface MessageOut { role: 'user' | 'tutor'; content: string; }
export interface Conversation {
  id: number; concept_id: number; attempt_logged: boolean;
  assistance_level: string; challenge_level: string; messages: MessageOut[];
}
export interface SendResult {
  reply: string; attempt_logged: boolean;
  assistance_level: string; challenge_level: string; events: EventOut[];
}
export interface Intent { goal: string; prior_knowledge: string; time_budget: string; }
export interface SourceDoc {
  id: number; title: string; url: string; tier: number;
  summary: string; why: string; rank: number; angle: string; status: string;
}
export interface Foundation { overview: string; key_concepts: string[]; prerequisite_map: Record<string, string[]>; }
export interface ResearchResult { foundation: Foundation; sources: SourceDoc[]; events: EventOut[]; }
export interface CreateTopicBody { title: string; goal: string; prior_knowledge?: string; time_budget?: string; }
export interface Item { id: number; text: string; type: string; status: string; position: number; }
export interface Deliverable { id: number; kind: string; text: string; acceptance_criteria: string[]; }
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
  baseline_id?: number | null; item_id?: number | null;
}
