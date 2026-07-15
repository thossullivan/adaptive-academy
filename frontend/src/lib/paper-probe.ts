export function unanswered(
  questions: { index: number }[],
  answers: Record<number, string>
): number {
  return questions.filter((q) => !(answers[q.index] ?? '').trim()).length;
}
