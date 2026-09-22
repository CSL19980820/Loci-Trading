/**
 * 定时台的目录读取与中文名解析。
 *
 * 一屏要六份数据：jobs（Colada 查询）、调度状态、战法目录、技能目录、模型提供方、
 * 自建额度。六份各自失败互不牵连，所以 load 用 allSettled，且只把第一条真失败写进
 * loadError；额度问不到只是少显示一行读数——老后端没有 /api/jobs/quota，把它算成
 * 加载失败等于把一个能用的页面说成坏的。
 *
 * 中文名解析跟着目录放，不留在组件里：显示名要靠 strategies / skills 建索引
 * （名册每行都要用，逐行 find 会随目录长度线性劣化），而目录就是这个文件拉的。
 */
import { computed, ref } from 'vue'

import {
  getJobQuota,
  getProviders,
  getScheduleStatus,
  getSkills,
  getStrategies,
} from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  Job,
  JobQuota,
  LlmProvider,
  ScheduleStatus,
  Skill,
  StrategyInfo,
} from '@/shared/types/quant'

import {
  isSkillBoundJob,
  isStrategyBoundJob,
  skillSlugFromBoundJob,
  strategySlugFromBoundJob,
} from './jobOwnership'
import { cnStrategyName } from './opsLabels'
import { useJobsQuery } from './useJobsQuery'
import { useVisitorMode } from '@/shared/composables/useAccess'

export function useJobsCatalog() {
  const visitor = useVisitorMode()
  const {
    jobs,
    isPending: jobsPending,
    error: jobsQueryError,
    refetch: refetchJobs,
  } = useJobsQuery()
  const schedule = ref<ScheduleStatus | null>(null)
  /** 自建任务额度：写在「新建」旁边，别让人填完一整张表才吃 429。 */
  const quota = ref<JobQuota | null>(null)
  const loadError = ref('')
  const strategies = ref<StrategyInfo[]>([])
  const skills = ref<Skill[]>([])
  const providers = ref<LlmProvider[]>([])

  const jobsError = computed(() => {
    const queryError = toErrorMessage(jobsQueryError.value, '定时任务加载失败')
    return queryError || loadError.value
  })

  async function load(): Promise<void> {
    loadError.value = ''
    const [
      jobsResult,
      scheduleResult,
      strategiesResult,
      skillsResult,
      providersResult,
      quotaResult,
    ] = await Promise.allSettled([
      refetchJobs(),
      getScheduleStatus(),
      getStrategies(),
      getSkills(),
      visitor.value ? Promise.resolve([]) : getProviders(),
      visitor.value ? Promise.resolve(null) : getJobQuota(),
    ])
    const failures = [
      [jobsResult, '定时任务加载失败'],
      [scheduleResult, '调度状态加载失败'],
      [strategiesResult, '战法列表加载失败'],
      [skillsResult, '技能列表加载失败'],
      [providersResult, '模型提供方加载失败'],
    ] as const
    const failed = failures.find(([result]) => result.status === 'rejected')
    if (failed?.[0].status === 'rejected') {
      loadError.value = toErrorMessage(failed[0].reason, failed[1])
    }
    if (scheduleResult.status === 'fulfilled') schedule.value = scheduleResult.value
    if (strategiesResult.status === 'fulfilled') strategies.value = strategiesResult.value
    if (skillsResult.status === 'fulfilled') skills.value = skillsResult.value
    if (providersResult.status === 'fulfilled') providers.value = providersResult.value
    // 额度问不到只是少显示一行「自建额度」，不该把整页判成加载失败：
    // 老后端没有 /api/jobs/quota，报错会把一个能用的页面说成坏的。
    quota.value = quotaResult.status === 'fulfilled' ? quotaResult.value : null
  }

  // displayName 由 v-for 每行调用，逐行 find 会随目录长度线性劣化；预建索引。
  // 存的是**已中文化**的名字：后端的 name 缺失或本身就是 slug 时，cnStrategyName
  // 会退回共享词表，界面上不会再冒出 `sanyuan-tail-v1` 这种英文编码。
  const strategyNames = computed(
    () => new Map(strategies.value.map((s) => [s.slug, cnStrategyName(s.name, s.slug)])),
  )
  const skillNames = computed(
    () => new Map(skills.value.map((s) => [s.slug, cnStrategyName(s.name, s.slug)])),
  )

  /**
   * 名字一律走中文：后端没回 name 时，旧代码 `|| slug` 直接把 `sanyuan-tail-v1`
   * 这种英文编码摆到界面上。现在统一过 cnStrategyName（含拼音词根兜底）。
   */
  function displayName(job: Job): string {
    if (isStrategyBoundJob(job)) {
      const slug = strategySlugFromBoundJob(job)
      return slug ? (strategyNames.value.get(slug) ?? cnStrategyName('', slug)) : job.name
    }
    if (isSkillBoundJob(job)) {
      const slug = skillSlugFromBoundJob(job)
      return slug ? (skillNames.value.get(slug) ?? cnStrategyName('', slug)) : job.name
    }
    return job.name
  }

  function selectedStrategyText(job: Job): string {
    const slug = String(job.config?.strategy || strategySlugFromBoundJob(job) || '')
    if (!slug) return '—'
    return strategyNames.value.get(slug) ?? cnStrategyName('', slug)
  }

  function selectedSkillText(job: Job): string {
    const slug = String(job.config?.skill || skillSlugFromBoundJob(job) || '')
    if (!slug) return '—'
    return skillNames.value.get(slug) ?? cnStrategyName('', slug)
  }

  return {
    jobs,
    jobsPending,
    jobsError,
    schedule,
    quota,
    strategies,
    skills,
    providers,
    load,
    displayName,
    selectedStrategyText,
    selectedSkillText,
  }
}
