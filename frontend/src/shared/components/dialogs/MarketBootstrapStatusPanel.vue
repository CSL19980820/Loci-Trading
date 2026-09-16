<script setup lang="ts">
import { computed } from 'vue'

/**
 * 行情初始化 / 补齐的状态面板。
 *
 * 版式是「事实格 + 一行状态 + 进度尺」：日期与路径是要核对的事实，用等宽数字排成格子；
 * 说明性长句一律不进正文（此前两段各 20+ 字的提示已压成事实项与 tooltip）。
 */
const props = defineProps<{
  isCatchup: boolean
  coverageLast: string
  expectedLast: string
  rangeLabel: string
  lagLabel: string
  running: boolean
  isDone: boolean
  isError: boolean
  leadText: string
  dataDirLabel: string
  error: string
  percent: number
  detail: string
  reportSummary: string
}>()

type BootFact = { key: string; label: string; value: string }

const facts = computed<BootFact[]>(() => {
  const out: BootFact[] = []
  out.push({
    key: 'coverage',
    label: '库内最新',
    value: props.coverageLast || (props.isCatchup ? '—' : '暂无日 K'),
  })
  if (props.isCatchup || props.expectedLast) {
    out.push({
      key: 'range',
      label: props.isCatchup ? '将补区间' : '目标覆盖至',
      value: props.isCatchup
        ? props.rangeLabel || props.expectedLast || '—'
        : props.expectedLast || '—',
    })
  }
  if (props.isCatchup && props.lagLabel) {
    out.push({ key: 'lag', label: '落后', value: props.lagLabel })
  }
  if (!props.isCatchup) {
    out.push({ key: 'scope', label: '范围', value: '全市场日线 · 10–40 分钟' })
  }
  out.push({ key: 'db', label: '写入', value: props.dataDirLabel })
  return out
})

const meterClass = computed(() => ({
  'seal-meter--done': props.isDone,
  'seal-meter--err': props.isError,
}))

const clampedPercent = computed(() => Math.min(100, Math.max(0, props.percent)))

/** 进度明细与完成回执压成一行等宽文本，别各占一段 */
const statusLine = computed(() =>
  [props.detail, props.isDone ? props.reportSummary : ''].filter(Boolean).join(' · '),
)
</script>

<template>
  <div class="boot-body flex min-w-0 flex-col gap-2">
    <dl class="boot-facts" aria-label="行情覆盖明细">
      <div v-for="fact in facts" :key="fact.key" class="boot-fact">
        <dt>{{ fact.label }}</dt>
        <dd :title="fact.value">{{ fact.value }}</dd>
      </div>
    </dl>

    <p class="boot-lead">{{ leadText }}</p>

    <div v-if="running || isDone" class="seal-meter" :class="meterClass" aria-label="同步进度">
      <div class="seal-meter__track">
        <div class="seal-meter__fill" :style="{ width: `${clampedPercent}%` }" />
      </div>
      <span class="seal-meter__pct">{{ Math.round(percent) }}%</span>
    </div>

    <p v-if="statusLine" class="boot-meta">{{ statusLine }}</p>

    <el-alert
      v-if="error"
      :title="error"
      :type="isError ? 'error' : 'warning'"
      show-icon
      :closable="false"
    />
  </div>
</template>

<style scoped>
/* 事实格：一格一件要核对的事，列宽 140px 起，格数不足不留硬空格 */
.boot-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--gap-2);
  margin: 0;
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet-alt);
}

.boot-fact {
  min-width: 0;
}

.boot-fact dt {
  color: var(--mist);
  font-size: var(--fs-kicker);
  letter-spacing: 0.06em;
}

.boot-fact dd {
  margin: 0;
  overflow: hidden;
  color: var(--ink);
  font: 600 var(--fs-body) / 1.35 var(--mono);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.boot-lead {
  margin: 0;
  color: var(--ink);
  font-size: var(--fs-body);
  line-height: 1.45;
}

.boot-meta {
  margin: 0;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}
</style>
