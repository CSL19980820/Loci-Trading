/**
 * 候选池的中文化文案。
 *
 * 用户要求界面任何位置都不许露英文编码：战法 slug、`sanyuan-tail-v1@2026-08-20`
 * 这样的池号、`job:screen` 这样的写入来源，三种都要过一遍。战法名要查目录，所以
 * 那两个函数由 usePoolLabels 按目录建索引后产出；来源与裁决色与目录无关，是纯函数。
 */
import { computed, type Ref } from 'vue'

import { strategyLabel as formatStrategyLabel, decisionLabel } from '@/shared/lib/format'
import type { StrategyInfo } from '@/shared/types/quant'

/** 战法名与池号：都要查目录，所以绑在同一份索引上。 */
export function usePoolLabels(strategies: Ref<StrategyInfo[]>) {
  const strategyNameBySlug = computed(() => {
    const map = new Map<string, string>()
    for (const item of strategies.value) {
      map.set(item.slug, item.name)
    }
    return map
  })

  function strategyLabel(slug: string): string {
    if (!slug) return '—'
    return strategyNameBySlug.value.get(slug) || formatStrategyLabel(slug)
  }

  /**
   * 池号形如 `sanyuan-tail-v1@2026-08-20`：拆出 slug 落中文，日期原样留。
   * 用户要求界面任何位置都不许再出现英文 slug（含这个详情抽屉）。
   */
  function poolLabel(value: string | null | undefined): string {
    const raw = String(value ?? '').trim()
    if (!raw) return '—'
    const [slug, day] = raw.split('@')
    const name = strategyLabel(slug)
    return day ? `${name} · ${day}` : name
  }

  return { strategyLabel, poolLabel }
}

/** 写入来源同理：内部编码不外露 */
const SOURCE_LABELS: Record<string, string> = {
  'job:screen': '盘后选股任务',
  'api:screen': '接口选股',
  'api:screen_today': '盘中选股',
  'api:screen_backfill': '历史回补',
  ai_assistant: '助手写入',
  manual: '手工录入',
}

export function sourceLabel(value: string | null | undefined): string {
  const raw = String(value ?? '').trim()
  if (!raw) return '—'
  if (SOURCE_LABELS[raw]) return SOURCE_LABELS[raw]
  if (raw.includes('backfill')) return '历史回补'
  if (raw.startsWith('job:')) return '定时任务'
  if (raw.startsWith('api:')) return '接口写入'
  return raw
}

export function decisionType(decision: string): 'info' | 'danger' {
  return decisionLabel(decision) === '精选' ? 'danger' : 'info'
}
