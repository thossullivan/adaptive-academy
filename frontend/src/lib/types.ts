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
