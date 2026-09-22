<script setup lang="ts">
/**
 * 定时台左栏：两个筛选 + 任务卡列表（Linear 式）。
 *
 * 每张卡：状态点 + 名称 + 来源徽标；第二行是人话调度（`工作日 15:05`）与上次结果。
 * 本组件**只负责显示与选中**：过滤后的数据、名字解析、cron 换算都在 JobsTab 里算好传进来。
 * 点卡除了改选中项还会 emit `pick`，父级在手机端用它打开详情 Sheet。
 */
import { Clock3 } from '@lucide/vue'

import type { JobHealth } from '../composables/opsLabels'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import UiBadge from '@/shared/components/ui/UiBadge.vue'

export type JobRailRow = {
  id: string
  /** 已解析过的展示名（战法/技能绑定任务显示战法名，不是 `screen:slug`） */
  title: string
  kindText: string
  originText: string
  bound: boolean
  enabled: boolean
  health: JobHealth
  healthText: string
  /** 人话调度，如「工作日 15:05」「仅手动」 */
  cronText?: string
  /** 上次运行时间（原文，`YYYY-MM-DD HH:mm:ss`） */
  lastRunAt?: string
}

defineProps<{
  rows: JobRailRow[]
}>()

const emit = defineEmits<{ pick: [id: string] }>()

const selectedId = defineModel<string | null>('selectedId', { required: true })
const kindFilter = defineModel<string>('kindFilter', { required: true })
const statusFilter = defineModel<string>('statusFilter', { required: true })

function pick(id: string): void {
  selectedId.value = id
  emit('pick', id)
}

function shortTime(raw?: string): string {
  const text = String(raw || '').trim()
  if (!text) return ''
  return text.replace('T', ' ').slice(5, 16)
}
</script>

<template>
  <aside class="jobs-rail">
    <div class="jobs-filters">
      <Select v-model="kindFilter">
        <SelectTrigger size="sm" class="jobs-filter" aria-label="按类型筛选">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部类型</SelectItem>
          <SelectItem value="sync">同步行情</SelectItem>
          <SelectItem value="screen">选股</SelectItem>
          <SelectItem value="skill">技能</SelectItem>
          <SelectItem value="notify">企微推送</SelectItem>
          <SelectItem value="outcome">其它</SelectItem>
        </SelectContent>
      </Select>
      <Select v-model="statusFilter">
        <SelectTrigger size="sm" class="jobs-filter" aria-label="按上次结果筛选">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部结果</SelectItem>
          <SelectItem value="failed">只看失败</SelectItem>
          <SelectItem value="ok">上次成功</SelectItem>
          <SelectItem value="skipped">上次跳过</SelectItem>
          <SelectItem value="never">从未跑过</SelectItem>
        </SelectContent>
      </Select>
    </div>
    <div class="jobs-list" role="listbox" aria-label="任务列表">
      <article
        v-for="row in rows"
        :key="row.id"
        role="option"
        tabindex="0"
        class="job-card"
        :class="{ 'is-active': row.id === selectedId, 'is-off': !row.enabled, [`is-${row.health}`]: true }"
        :aria-selected="row.id === selectedId"
        :aria-label="`${row.title} · ${row.healthText}`"
        @click="pick(row.id)"
        @keydown.enter.prevent="pick(row.id)"
        @keydown.space.prevent="pick(row.id)"
      >
        <span class="job-card__dot" :title="row.healthText" aria-hidden="true" />
        <div class="job-card__body">
          <div class="job-card__top">
            <strong class="job-card__title">{{ row.title }}</strong>
            <UiBadge :variant="row.bound ? 'info' : 'secondary'" class="job-card__origin">{{ row.originText }}</UiBadge>
          </div>
          <div class="job-card__meta">
            <span class="job-card__sched">
              <Clock3 aria-hidden="true" />
              {{ row.cronText || row.kindText }}
            </span>
            <span v-if="!row.enabled" class="job-card__off">已停用</span>
            <span v-else class="job-card__health" :class="`job-card__health--${row.health}`">
              {{ row.healthText }}<template v-if="row.lastRunAt"> · {{ shortTime(row.lastRunAt) }}</template>
            </span>
          </div>
        </div>
      </article>
      <EmptyState v-if="!rows.length" compact description="没有匹配的任务" reason="调整类型或结果筛选" />
    </div>
  </aside>
</template>

<style scoped>
.jobs-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-width: 0;
  min-height: 0;
}

.jobs-filters {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--gap-2);
}

.jobs-filter {
  width: 100%;
  min-width: 0;
}

.jobs-list {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  padding: 2px;
}

.job-card {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-2);
  min-width: 0;
  padding: var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.job-card:hover {
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
}

.job-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.job-card.is-active {
  border-color: var(--seal-border);
  background: color-mix(in oklab, var(--seal-soft) 60%, var(--surface));
  box-shadow: 0 0 0 1px var(--seal-border);
}

.job-card.is-off {
  opacity: 0.72;
}

.job-card__dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--border-strong);
}

.job-card.is-ok .job-card__dot {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}

.job-card.is-failed .job-card__dot {
  background: var(--stamp);
  box-shadow: 0 0 0 3px var(--stamp-soft);
}

.job-card.is-skipped .job-card__dot {
  background: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-soft);
}

.job-card.is-running .job-card__dot {
  background: var(--info);
  box-shadow: 0 0 0 3px var(--info-soft);
  animation: job-pulse 1.4s ease-in-out infinite;
}

/* 从未跑过是空心圈：它不是「好」，也不是「坏」，是「还没有过」。 */
.job-card.is-never .job-card__dot {
  background: transparent;
  border: 1.5px solid var(--border-strong);
}

.job-card__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.job-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  min-width: 0;
}

.job-card__title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.job-card__origin {
  flex: 0 0 auto;
}

.job-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 2px var(--gap-2);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.job-card__sched {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: var(--text-secondary);
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.job-card__sched :deep(svg) {
  width: 12px;
  height: 12px;
  color: var(--text-tertiary);
}

.job-card__health {
  font-variant-numeric: tabular-nums;
}

.job-card__health--failed {
  color: var(--stamp);
  font-weight: 600;
}

.job-card__health--skipped {
  color: var(--warn-ink);
}

.job-card__health--ok {
  color: var(--ok);
}

.job-card__off {
  color: var(--text-tertiary);
}

@keyframes job-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 3px var(--info-soft);
  }
  50% {
    box-shadow: 0 0 0 6px transparent;
  }
}

@media (prefers-reduced-motion: reduce) {
  .job-card.is-running .job-card__dot {
    animation: none;
  }
}
</style>
