<script setup lang="ts">
/**
 * 定时台左栏：两个筛选 + 任务名册。
 *
 * 拆出来的原因有两个，第一个才是主要的：
 * 1. 行上现在有**状态点 + 上次结果**。以前一行只写类型与启用态，`last_status`
 *  根本不露脸，找「哪条挂了」只能逐条点开看——这一屏是「看任务为什么失败」
 *    的第一跳，值得单独一个文件。
 * 2. JobsTab 本体已经装了 CRUD、配额、回执与跳转，再塞一屏名册就过 600 行了。
 *
 * 本组件**只负责显示与选中**：过滤后的数据、名字解析都在 JobsTab 里算好传进来。
 */
import type { JobHealth } from '../composables/opsLabels'

import EmptyState from '@/shared/components/ui/EmptyState.vue'

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
}

defineProps<{
  rows: JobRailRow[]
}>()

const selectedId = defineModel<string | null>('selectedId', { required: true })
const kindFilter = defineModel<string>('kindFilter', { required: true })
const statusFilter = defineModel<string>('statusFilter', { required: true })
</script>

<template>
  <aside class="jobs-rail">
    <div class="jobs-filters">
      <el-select v-model="kindFilter" size="small" class="jobs-filter" aria-label="按类型筛选">
        <el-option label="全部类型" value="all" />
        <el-option label="同步行情" value="sync" />
        <el-option label="选股" value="screen" />
        <el-option label="技能" value="skill" />
        <el-option label="企微推送" value="notify" />
        <el-option label="其它" value="outcome" />
      </el-select>
      <el-select
        v-model="statusFilter"
        size="small"
        class="jobs-filter"
        aria-label="按上次结果筛选"
      >
        <el-option label="全部结果" value="all" />
        <el-option label="只看失败" value="failed" />
        <el-option label="上次成功" value="ok" />
        <el-option label="上次跳过" value="skipped" />
        <el-option label="从未跑过" value="never" />
      </el-select>
    </div>
    <el-scrollbar class="jobs-list-scroll">
      <div
        v-for="row in rows"
        :key="row.id"
        role="button"
        tabindex="0"
        class="job-row"
        :class="{ active: row.id === selectedId }"
        @click="selectedId = row.id"
        @keydown.enter.prevent="selectedId = row.id"
        @keydown.space.prevent="selectedId = row.id"
      >
        <div class="job-row-top">
          <span class="job-dot" :class="`job-dot--${row.health}`" :title="row.healthText" />
          <strong>{{ row.title }}</strong>
          <el-tag size="small" effect="light" :type="row.bound ? 'info' : 'danger'">
            {{ row.originText }}
          </el-tag>
        </div>
        <div class="job-row-meta">
          <span>{{ row.kindText }}</span>
          <span :class="row.enabled ? 'on' : 'off'">{{ row.enabled ? '启用' : '停用' }}</span>
          <span class="job-row-health" :class="`job-row-health--${row.health}`">
            {{ row.healthText }}
          </span>
        </div>
      </div>
      <EmptyState v-if="!rows.length" description="这个筛选下没有任务，换上面的两个筛选看看" />
    </el-scrollbar>
  </aside>
</template>

<style scoped>
.jobs-rail {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-height: 0;
  border-right: 1px solid var(--rule);
  padding-right: 0.65rem;
}

.jobs-filters {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem;
  flex-shrink: 0;
}

.jobs-filter {
  width: 100%;
  min-width: 0;
  flex-shrink: 0;
}

.jobs-list-scroll {
  flex: 1 1 auto;
  min-height: 0;
}

.job-row {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  color: inherit;
  border-radius: 6px;
  padding: 0.55rem 0.6rem;
  margin-bottom: 0.25rem;
  cursor: pointer;
}

.job-row:hover {
  background: color-mix(in srgb, var(--panel) 80%, var(--rule));
}

/* 全局焦点环只覆盖原生控件，自绘行要自己补，否则键盘用户看不见选到了哪一行 */
.job-row:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: -2px;
}

.job-row.active {
  border-color: var(--rule);
  background: var(--seal-soft);
}

.job-row-top {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.job-row-top strong {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 0.92rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-row-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.35rem;
  margin-top: 0.25rem;
  font-size: 0.78rem;
  color: var(--muted);
}

.job-row-meta .on {
  color: var(--success);
}

.job-row-meta .off {
  color: var(--muted);
}

/*
 * 状态点。语义色一律取 EP 的 --el-color-*（全站的错误/成功都用这套），
 * **不借 --up / --down 涨跌色**：涨跌说的是价格方向，任务成败是另一回事，
 * 借过来会让「红」在两个页面里意思相反。
 */
.job-dot {
  flex: 0 0 auto;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--rule);
}

.job-dot--ok {
  background: var(--el-color-success);
}

.job-dot--failed {
  background: var(--el-color-danger);
}

.job-dot--skipped {
  background: var(--el-color-warning);
}

.job-dot--running {
  background: var(--info);
}

/* 从未跑过是空心圈：它不是「好」，也不是「坏」，是「还没有过」。 */
.job-dot--never {
  background: transparent;
  border: 1px solid var(--line-2);
}

.job-row-health {
flex: 0 0 auto;
}

.job-row-health--failed {
  color: var(--el-color-danger);
  font-weight: 600;
}

.job-row-health--skipped {
  color: var(--el-color-warning);
}

.job-row-health--never {
  color: var(--mist);
}

@media (max-width: 800px) {
  .jobs-rail {
    border-right: none;
    padding-right: 0;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.65rem;
    max-height: 14rem;
  }
}
</style>
