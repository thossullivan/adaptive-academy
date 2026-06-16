import type { Conversation, SendResult, Topic } from './types';

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
    }).then(j<SendResult>)
};
