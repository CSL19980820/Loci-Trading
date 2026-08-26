/** Memory quota caps and grouping — pure helpers for settings UI. */

export const MEMORY_QUOTAS = {
  user: 2200,
  memory: 4000,
} as const

export type MemoryTarget = 'user' | 'memory'

export type MemoryLike = {
  id: string
  target: MemoryTarget
  content: string
  source?: string
}

export function memoryUsagePct(used: number, cap: number): number {
  if (cap <= 0) return 0
  return Math.min(100, Math.round((Math.max(0, used) / cap) * 100))
}

export function groupMemoriesByTarget<T extends MemoryLike>(
  items: T[],
): { user: T[]; memory: T[] } {
  const user: T[] = []
  const memory: T[] = []
  for (const item of items) {
    if (item.target === 'user') user.push(item)
    else memory.push(item)
  }
  return { user, memory }
}

/** Join one warehouse into a single markdown document for the settings editor. */
export function joinMemoryDocument<T extends MemoryLike>(items: T[]): string {
  return items
    .map((item) => item.content.trim())
    .filter(Boolean)
    .join('\n\n')
}
