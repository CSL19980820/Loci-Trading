/**
 * 定时任务归属：战法/技能绑定 vs 本机任务。
 * 绑定权威键与后端一致：`screen:{slug}` / `skill:{slug}`。
 */
import type { Job } from '@/shared/types/quant'

export function isStrategyBoundJob(job: Pick<Job, 'name' | 'kind'>): boolean {
  return job.kind === 'screen' && job.name.startsWith('screen:')
}

export function isSkillBoundJob(job: Pick<Job, 'name' | 'kind'>): boolean {
  return job.kind === 'skill' && job.name.startsWith('skill:')
}

/** 战法或技能详情绑定的任务（定时台只读，改配置走详情） */
export function isBoundManagedJob(job: Pick<Job, 'name' | 'kind'>): boolean {
  return isStrategyBoundJob(job) || isSkillBoundJob(job)
}

export function strategySlugFromBoundJob(job: Pick<Job, 'name'>): string {
  return job.name.startsWith('screen:') ? job.name.slice('screen:'.length) : ''
}

export function skillSlugFromBoundJob(job: Pick<Job, 'name'>): string {
  return job.name.startsWith('skill:') ? job.name.slice('skill:'.length) : ''
}

/** 禁止本机新建/改名占用绑定前缀 */
export function isReservedStrategyJobName(name: string): boolean {
  const lower = name.trim().toLowerCase()
  return lower.startsWith('screen:') || lower.startsWith('skill:')
}

export function jobOriginLabel(job: Pick<Job, 'name' | 'kind'>): '战法' | '技能' | '本机' {
  if (isStrategyBoundJob(job)) return '战法'
  if (isSkillBoundJob(job)) return '技能'
  return '本机'
}
