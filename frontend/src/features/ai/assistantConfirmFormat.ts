import type { AiHitlAsk, AiHitlQuestion } from '@/shared/types/ai_assistant'

/** Structured reply body for POST .../messages after multi-question HITL. */
export function formatAskAnswers(
  questions: AiHitlQuestion[],
  answers: Record<string, string>,
): string {
  return questions
    .map((question, index) => {
      const answer = (answers[question.id] || '').trim()
      return `${index + 1}. [${question.id}] ${question.prompt} → ${answer}`
    })
    .join('\n')
}

export function questionNeedsAnswer(question: AiHitlQuestion): boolean {
  const hasOptions = Boolean(question.options?.length)
  const free = question.allow_free_text === true || !hasOptions
  return hasOptions || free
}

export function missingRequiredAnswers(
  questions: AiHitlQuestion[],
  answers: Record<string, string>,
): string[] {
  return questions
    .filter((question) => questionNeedsAnswer(question))
    .filter((question) => !(answers[question.id] || '').trim())
    .map((question) => question.id)
}

export function isMultiAsk(ask?: AiHitlAsk | null): boolean {
  return Boolean(ask?.questions?.length)
}
