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
