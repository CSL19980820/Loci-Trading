<script setup lang="ts">
/**
 * 定时台左栏：两个筛选 + 任务名册。
 *
 * 每行：健康点 · 名称（绑定任务带来源标）· 人话调度；右侧是下次触发与上次结果。
 * 本组件只负责显示与选中：名字、调度换算、下次触发都在 JobsTab 算好传进来。
 * 点行除了改选中项还会 emit `pick`，父级在窄屏用它打开详情 Sheet。
 */
import { Command, CommandItem, CommandList } from '@/shared/components/ui/command'

import type { JobHealth } from '../composables/opsLabels'
import { relativeDayTime } from '../composables/jobPresentation'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'

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
  /** 整句人话调度，如「工作日 15:05」「仅手动」 */
  cronText?: string
  /** 调度的星期部分：「工作日」「每天」 */
  dayText?: string
  /** 调度的时点部分：「15:05」「盘中每 5 分钟 · 15:00」 */
  bodyText?: string
  /** 下次触发（原文 ISO） */
  nextRunAt?: string
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

const HEALTH_GLYPH: Record<JobHealth, string> = {
  ok: '✓',
  failed: '✗',
  skipped: '↷',
  running: '…',
  never: '○',
}

function pick(id: string): void {
  selectedId.value = id
  emit('pick', id)
}

function shortTime(raw?: string): string {
  const text = String(raw || '').trim()
  if (!text) return ''
  return text.replace('T', ' ').slice(5, 16)
}

function nextLabel(row: JobRailRow): string {
  if (!row.enabled) return '已停用'
  if (!row.nextRunAt) return row.dayText === '仅手动' ? '仅手动' : '—'
  return relativeDayTime(row.nextRunAt) || '—'
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
    <Command :model-value="selectedId ?? undefined" class="jobs-command" :selection-follows-focus="false">
      <CommandList class="jobs-list" aria-label="任务列表">
        <CommandItem
          v-for="row in rows"
          :key="row.id"
          :value="row.id"
          :text-value="row.title"
          class="job-row"
          :class="{ 'is-active': row.id === selectedId, 'is-off': !row.enabled, [`is-${row.health}`]: true }"
          :aria-label="`${row.title} · ${row.healthText}`"
          @select="pick(row.id)"
        >
          <span class="job-row__dot" :title="row.healthText" aria-hidden="true" />
          <span class="job-row__main">
            <span class="job-row__title">
              <strong>{{ row.title }}</strong>
              <span v-if="row.bound" class="job-row__origin">{{ row.originText }}</span>
            </span>
            <span class="job-row__sched" :title="row.cronText">
              <span v-if="row.dayText" class="job-row__day">{{ row.dayText }}</span>
              <span class="job-row__body">{{ row.bodyText || row.kindText }}</span>
            </span>
          </span>
          <span class="job-row__side">
            <span class="job-row__next" :class="{ 'is-muted': !row.enabled || !row.nextRunAt }">{{ nextLabel(row) }}</span>
            <span class="job-row__last" :class="`is-${row.health}`" :title="row.healthText">
              <i aria-hidden="true">{{ HEALTH_GLYPH[row.health] }}</i>{{ shortTime(row.lastRunAt) || row.healthText }}
            </span>
          </span>
        </CommandItem>
        <EmptyState v-if="!rows.length" compact description="没有匹配的任务" />
      </CommandList>
    </Command>
  </aside>
</template>

<style scoped>
.jobs-rail {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.jobs-filters {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 6px;
  padding: 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.jobs-filter {
  width: 100%;
  min-width: 0;
  border-color: transparent;
  background: var(--surface-sunken);
  box-shadow: none;
}

.jobs-command {
  flex: 1;
  min-height: 0;
  background: transparent;
}

.jobs-list {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  max-height: none;
  min-height: 0;
  padding: 4px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.jobs-list :deep([role='presentation']) {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.job-row {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 9px 10px 9px 12px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}

.job-row:hover,
.job-row[data-highlighted] {
  background: var(--surface-hover);
}

.job-row[data-highlighted] {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.job-row.is-active {
  background: color-mix(in oklab, var(--seal-soft) 70%, var(--surface));
}

.job-row.is-active::before {
  content: '';
  position: absolute;
  inset-block: 10px;
  left: 0;
  width: 2px;
  border-radius: 2px;
  background: var(--seal);
}

.job-row.is-off .job-row__main,
.job-row.is-off .job-row__side {
  opacity: 0.55;
}

.job-row__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-strong);
}

.job-row.is-ok .job-row__dot { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); }
.job-row.is-failed .job-row__dot { background: var(--stamp); box-shadow: 0 0 0 3px var(--stamp-soft); }
.job-row.is-skipped .job-row__dot { background: var(--warn); box-shadow: 0 0 0 3px var(--warn-soft); }
.job-row.is-running .job-row__dot { background: var(--info); animation: job-pulse 1.4s ease-in-out infinite; }
.job-row.is-never .job-row__dot { background: transparent; box-shadow: inset 0 0 0 1.5px var(--border-strong); }

.job-row__main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.job-row__title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.job-row__title strong {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-row__origin {
  flex: none;
  padding: 0 5px;
  border-radius: var(--radius-xs);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-size: var(--fs-micro);
  font-weight: 600;
  line-height: 16px;
}

.job-row__sched {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.job-row__day {
  flex: none;
  color: var(--text-secondary);
}

.job-row__body {
  min-width: 0;
  overflow: hidden;
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-row__side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
  min-width: 0;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.job-row__next {
  color: var(--text-primary);
  font-size: var(--fs-aux);
  font-weight: 600;
}

.job-row__next.is-muted {
  color: var(--text-tertiary);
  font-family: var(--font);
  font-weight: 500;
}

.job-row__last {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.job-row__last i {
  font-style: normal;
  font-weight: 700;
}

.job-row__last.is-ok i { color: var(--ok); }
.job-row__last.is-failed { color: var(--stamp); }
.job-row__last.is-skipped i { color: var(--warn); }
.job-row__last.is-running i { color: var(--info); }

@keyframes job-pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--info-soft); }
  50% { box-shadow: 0 0 0 6px transparent; }
}

@media (prefers-reduced-motion: reduce) {
  .job-row.is-running .job-row__dot { animation: none; }
}
</style>
