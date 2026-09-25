<script setup lang="ts">
/**
 * 候选详情：身份与评分 → 选出后走势 → 理由 → 事实 → 战法足迹 → 证据。
 *
 * 选出后走势用日线现算：基准是选出日（含）之前最后一根收盘，读数与迷你图都只描述
 * 已发生的行情。战法 / 池 / 来源三处文案由页面解析后传入；删除与看档案都往外抛。
 */
import { computed } from 'vue'
import { ArrowUpRight, Trash2 } from '@lucide/vue'

import { useQuotesQuery } from '@/features/market/composables/useQuotesQuery'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/shared/components/ui/accordion'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Skeleton } from '@/shared/components/ui/skeleton'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { formatDateTime } from '@/shared/lib/dateTime'
import { decisionLabel, timingLabel } from '@/shared/lib/format'
import type { OpenBatchInput } from '@/shared/stores/batchBrowse'
import type { Candidate } from '@/shared/types/palace'

import StrategyFootprint from './StrategyFootprint.vue'
import { useStrategyFootprints } from '../composables/useStrategyFootprints'

const props = defineProps<{
  candidate: Candidate | null
  /** 战法中文名（页面查目录解析好） */
  strategyText: string
  /** 池号：战法中文名 · 候选日 */
  poolText: string
  /** 写入来源中文名 */
  sourceText: string
  batch: Omit<OpenBatchInput, 'focusCode'> | null
}>()

const emit = defineEmits<{ delete: [row: Candidate]; archive: [date?: string] }>()

const open = defineModel<boolean>({ required: true })

const liveCode = computed(() => (open.value ? String(props.candidate?.code || '').trim() : ''))

const { quote, isPending: quotePending } = useQuotesQuery(liveCode, () => ({
  adjust: 'qfq',
  limit: 260,
  enabled: Boolean(liveCode.value),
}))

const footprints = useStrategyFootprints(liveCode)

const tone = computed<'pick' | 'watch' | 'drop'>(() => {
  const label = decisionLabel(props.candidate?.decision ?? '')
  if (label === '精选') return 'pick'
  if (label === '观察') return 'watch'
  return 'drop'
})

const scoreValue = computed(() => {
  const raw = props.candidate?.score
  if (raw == null || !Number.isFinite(Number(raw))) return null
  return Number(raw)
})

const scoreText = computed(() => {
  const n = scoreValue.value
  if (n == null) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
})

/** 0–100 的评分画成环；量纲不明的分数只给数字 */
const scoreRing = computed(() => {
  const n = scoreValue.value
  if (n == null || n < 0 || n > 100) return null
  const circumference = 2 * Math.PI * 22
  return { dash: `${(n / 100) * circumference} ${circumference}` }
})

type Perf = {
  ret: number
  best: number | null
  worst: number | null
  days: number
  path: string
  area: string
  markX: number
  markY: number
  lastDate: string
}

const SPARK_W = 600
const SPARK_H = 72
const SPARK_PAD = 6

const perf = computed<Perf | null>(() => {
  const bars = quote.value?.bars ?? []
  const date = String(props.candidate?.date || '').slice(0, 10)
  if (!bars.length || !date) return null
  let baseIndex = -1
  for (let i = bars.length - 1; i >= 0; i -= 1) {
    if (String(bars[i]!.trade_date || '').slice(0, 10) <= date) {
      baseIndex = i
      break
    }
  }
  if (baseIndex < 0) return null
  const base = Number(bars[baseIndex]!.close)
  if (!Number.isFinite(base) || base <= 0) return null
  const after = bars.slice(baseIndex + 1)
  const last = Number(bars[bars.length - 1]!.close)
  const highs = after.map((bar) => Number(bar.high)).filter(Number.isFinite)
  const lows = after.map((bar) => Number(bar.low)).filter(Number.isFinite)

  const from = Math.max(0, baseIndex - 24)
  const closes: number[] = []
  for (const bar of bars.slice(from)) {
    const value = Number(bar.close)
    closes.push(Number.isFinite(value) ? value : (closes.at(-1) ?? base))
  }
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const spread = max - min || 1
  const step = closes.length > 1 ? SPARK_W / (closes.length - 1) : 0
  const points = closes.map((value, index) => [
    index * step,
    SPARK_PAD + (1 - (value - min) / spread) * (SPARK_H - SPARK_PAD * 2),
  ] as const)
  const markIndex = baseIndex - from
  const mark = points[markIndex] ?? points[0]!
  const path = points.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const tail = points.slice(markIndex)
  const area = tail.length > 1
    ? `M${mark[0].toFixed(1)},${SPARK_H} ${tail.map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join(' ')} L${tail.at(-1)![0].toFixed(1)},${SPARK_H} Z`
    : ''

  return {
    ret: Number.isFinite(last) ? (last / base - 1) * 100 : 0,
    best: highs.length ? (Math.max(...highs) / base - 1) * 100 : null,
    worst: lows.length ? (Math.min(...lows) / base - 1) * 100 : null,
    days: after.length,
    path,
    area,
    markX: mark[0],
    markY: mark[1],
    lastDate: String(bars[bars.length - 1]!.trade_date || '').slice(0, 10),
  }
})

function pct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function toneOf(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || Math.abs(value) < 0.005) return 'is-flat'
  return value > 0 ? 'is-up' : 'is-down'
}

const facts = computed(() => {
  const c = props.candidate
  if (!c) return []
  return [
    { key: '选出日', value: c.date, mono: true },
    { key: '时点', value: timingLabel(c.timing) },
    { key: '池', value: props.poolText },
    { key: '来源', value: props.sourceText },
    { key: '写入', value: formatDateTime(c.created_at), mono: true },
  ]
})

const evidence = computed(() =>
  Object.entries(props.candidate?.evidence ?? {}).map(([key, raw]) => {
    const value = typeof raw === 'string' ? raw : JSON.stringify(raw)
    return { key, value, wide: value.length > 36 }
  }),
)
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="cand flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[760px]">
      <DialogHeader class="cand__hero text-left" :class="`is-${tone}`">
        <div class="cand__id">
          <div v-if="candidate" class="cand__kicker">
            <span class="cand__verdict">{{ decisionLabel(candidate.decision) }}</span>
            <span class="cand__strategy">{{ strategyText }}</span>
            <span class="cand__date">{{ candidate.date }}</span>
          </div>
          <DialogTitle class="cand__title">
            <template v-if="candidate">
              <StockLink
                :code="candidate.code"
                :name="candidate.name"
                :date="candidate.date"
                :batch="batch"
                :show-code="false"
                class="cand__link"
              />
              <span class="cand__code">{{ candidate.code }}</span>
            </template>
            <template v-else>候选详情</template>
          </DialogTitle>
          <DialogDescription class="sr-only">候选详情</DialogDescription>
        </div>
        <div v-if="candidate" class="cand__score" :aria-label="`评分 ${scoreText}`">
          <svg v-if="scoreRing" viewBox="0 0 52 52" class="cand__ring" aria-hidden="true">
            <circle cx="26" cy="26" r="22" class="cand__ring-track" />
            <circle cx="26" cy="26" r="22" class="cand__ring-fill" :stroke-dasharray="scoreRing.dash" />
          </svg>
          <span class="cand__score-num">{{ scoreText }}</span>
          <span class="cand__score-label">评分</span>
        </div>
      </DialogHeader>

      <div v-if="candidate" class="cand__body">
        <section class="cand__perf" aria-label="选出后走势">
          <dl class="cand__perf-nums">
            <div class="cand__perf-main">
              <dt>选出后</dt>
              <dd :class="toneOf(perf?.ret)">
                <Skeleton v-if="quotePending && !perf" class="h-6 w-20" />
                <template v-else>{{ pct(perf?.ret) }}</template>
              </dd>
            </div>
            <div>
              <dt>最高</dt>
              <dd :class="toneOf(perf?.best)">{{ pct(perf?.best) }}</dd>
            </div>
            <div>
              <dt>最深</dt>
              <dd :class="toneOf(perf?.worst)">{{ pct(perf?.worst) }}</dd>
            </div>
            <div>
              <dt>已过</dt>
              <dd>{{ perf ? `${perf.days} 日` : '—' }}</dd>
            </div>
          </dl>
          <svg
            v-if="perf"
            class="cand__spark"
            :class="toneOf(perf.ret)"
            :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
            preserveAspectRatio="none"
            role="img"
            :aria-label="`选出后 ${pct(perf.ret)}，截至 ${perf.lastDate}`"
          >
            <path v-if="perf.area" :d="perf.area" class="cand__spark-area" />
            <line :x1="perf.markX" :x2="perf.markX" y1="0" :y2="SPARK_H" class="cand__spark-mark" />
            <path :d="perf.path" class="cand__spark-line" />
          </svg>
          <div v-else class="cand__spark cand__spark--empty" aria-hidden="true" />
        </section>

        <blockquote class="cand__reason" :class="{ 'is-empty': !candidate.reason }">
          {{ candidate.reason || '—' }}
        </blockquote>

        <dl class="cand__facts">
          <div v-for="fact in facts" :key="fact.key" class="cand__fact">
            <dt>{{ fact.key }}</dt>
            <dd :class="{ 'is-mono': fact.mono }" :title="fact.value">{{ fact.value || '—' }}</dd>
          </div>
        </dl>

        <StrategyFootprint
          compact
          :lanes="footprints.lanes.value"
          :loading="footprints.loading.value"
          :focus-date="candidate.date"
          @pick="(date) => emit('archive', date)"
        />

        <Accordion v-if="evidence.length" type="single" collapsible class="cand__evidence">
          <AccordionItem value="evidence" class="border-0">
            <AccordionTrigger class="cand__evidence-trigger">
              证据
              <span class="cand__evidence-count">{{ evidence.length }}</span>
            </AccordionTrigger>
            <AccordionContent class="pb-0">
              <dl class="cand__ev-grid">
                <div v-for="item in evidence" :key="item.key" class="cand__ev" :class="{ 'is-wide': item.wide }">
                  <dt>{{ item.key }}</dt>
                  <dd>{{ item.value }}</dd>
                </div>
              </dl>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      <DialogFooter class="cand__foot">
        <Button
          v-if="candidate"
          variant="ghost"
          size="sm"
          class="cand__delete"
          @click="emit('delete', candidate)"
        >
          <Trash2 aria-hidden="true" />
          删除
        </Button>
        <Button access="read" variant="outline" size="sm" @click="open = false">关闭</Button>
        <Button v-if="candidate" access="read" size="sm" @click="emit('archive')">
          档案
          <ArrowUpRight aria-hidden="true" />
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.cand {
  display: flex;
  flex-direction: column;
  max-height: 90dvh;
  overflow: hidden;
}

/* ─── 头：裁决色一抹渐变，名称大字，右侧评分环 ─── */
.cand__hero {
  --cand-accent: var(--text-tertiary);
  position: relative;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-4);
  flex-shrink: 0;
  padding: 22px 56px 18px 24px;
  background:
    radial-gradient(120% 140% at 0% 0%, color-mix(in oklab, var(--cand-accent) 13%, transparent), transparent 62%),
    var(--surface);
  border-bottom: 1px solid var(--border-subtle);
}

.cand__hero.is-pick { --cand-accent: var(--seal); }
.cand__hero.is-watch { --cand-accent: var(--warn); }

.cand__id {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.cand__kicker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.cand__verdict {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--radius-pill);
  background: color-mix(in oklab, var(--cand-accent) 14%, transparent);
  color: color-mix(in oklab, var(--cand-accent) 78%, var(--text-primary));
  font-size: var(--fs-kicker);
  font-weight: 600;
}

.cand__verdict::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.cand__strategy {
  color: var(--text-secondary);
  font-weight: 500;
}

.cand__date {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.cand__title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  margin: 0;
  min-width: 0;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.cand__link {
  color: var(--text-primary);
}

.cand__code {
  color: var(--text-tertiary);
  font: 500 var(--fs-ui) / 1 var(--mono);
  letter-spacing: 0.02em;
}

.cand__score {
  position: relative;
  display: grid;
  flex: none;
  place-items: center;
  width: 64px;
  height: 64px;
}

.cand__ring {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.cand__ring-track {
  fill: none;
  stroke: var(--border-subtle);
  stroke-width: 3;
}

.cand__ring-fill {
  fill: none;
  stroke: var(--cand-accent);
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dasharray var(--dur) var(--ease);
}

.cand__score-num {
  grid-area: 1 / 1;
  margin-top: -8px;
  color: var(--text-primary);
  font: 650 20px / 1 var(--mono);
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.cand__score-label {
  grid-area: 1 / 1;
  margin-top: 26px;
  color: var(--text-tertiary);
  font-size: var(--fs-micro);
}

/* ─── 正文 ─── */
.cand__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  min-height: 0;
  padding: 18px 24px 20px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.cand__perf {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 20px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-canvas);
}

.cand__perf-nums {
  display: grid;
  grid-template-columns: repeat(3, auto);
  gap: 10px 18px;
  margin: 0;
}

.cand__perf-nums > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.cand__perf-main {
  grid-column: 1 / -1;
}

.cand__perf-nums dt {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.cand__perf-nums dd {
  margin: 0;
  color: var(--text-primary);
  font: 600 var(--fs-ui) / 1.1 var(--mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.cand__perf-main dd {
  font-size: 26px;
  letter-spacing: -0.03em;
}

.is-up { color: var(--up); }
.is-down { color: var(--down); }
.cand__perf-nums dd.is-up { color: var(--up); }
.cand__perf-nums dd.is-down { color: var(--down); }

.cand__spark {
  width: 100%;
  height: 72px;
  overflow: visible;
  color: var(--flat);
}

.cand__spark.is-up { color: var(--up); }
.cand__spark.is-down { color: var(--down); }

.cand__spark--empty {
  border-radius: var(--radius);
  background: repeating-linear-gradient(90deg, var(--border-subtle) 0 1px, transparent 1px 24px);
  opacity: 0.6;
}

.cand__spark-line {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linejoin: round;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
}

.cand__spark-area {
  fill: currentColor;
  opacity: 0.1;
}

.cand__spark-mark {
  stroke: var(--text-tertiary);
  stroke-width: 1;
  stroke-dasharray: 3 3;
  vector-effect: non-scaling-stroke;
}

.cand__reason {
  margin: 0;
  padding: 2px 0 2px 14px;
  border-left: 2px solid var(--seal-border);
  color: var(--text-primary);
  font-size: var(--fs-body);
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.cand__reason.is-empty {
  color: var(--text-tertiary);
  border-left-color: var(--border-subtle);
}

.cand__facts {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 0;
  border-block: 1px solid var(--border-subtle);
}

.cand__fact {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
}

.cand__fact + .cand__fact {
  border-left: 1px solid var(--border-subtle);
}

.cand__fact:first-child {
  padding-left: 0;
}

.cand__fact dt {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.cand__fact dd {
  margin: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--fs-aux);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cand__fact dd.is-mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.cand__evidence {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 0 14px;
}

.cand__evidence-trigger {
  padding-block: 10px;
  font-size: var(--fs-ui);
  font-weight: 600;
}

.cand__evidence-count {
  margin-left: 8px;
  margin-right: auto;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  font: 600 var(--fs-kicker) / 18px var(--mono);
}

.cand__ev-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 0 0 14px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--border-subtle);
}

.cand__ev {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 8px 10px;
  background: var(--surface);
}

.cand__ev.is-wide {
  grid-column: 1 / -1;
}

.cand__ev dt {
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1.3 var(--mono);
}

.cand__ev dd {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-aux);
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* ─── 底栏 ─── */
.cand__foot {
  display: flex;
  flex-direction: row;
  flex-shrink: 0;
  align-items: center;
  justify-content: flex-end;
  gap: var(--gap-2);
  padding: 12px 24px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-canvas);
}

.cand__delete {
  margin-right: auto;
  color: var(--text-tertiary);
}

.cand__delete:hover {
  color: var(--stamp);
  background: var(--stamp-soft);
}

@media (max-width: 640px) {
  .cand__hero {
    padding: 16px 48px 14px 16px;
  }

  .cand__title {
    font-size: 19px;
  }

  .cand__score {
    width: 54px;
    height: 54px;
  }

  .cand__body {
    padding: 14px 16px 16px;
    gap: 14px;
  }

  .cand__perf {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .cand__perf-nums {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .cand__facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .cand__fact,
  .cand__fact:first-child {
    padding: 8px 0;
  }

  .cand__fact + .cand__fact {
    border-left: 0;
  }

  .cand__fact:last-child {
    grid-column: 1 / -1;
  }

  .cand__ev-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .cand__foot {
    padding: 10px 16px calc(10px + env(safe-area-inset-bottom, 0));
  }

  .cand__foot > :deep(button) {
    flex: 1 1 0;
  }

  .cand__delete {
    margin-right: 0;
  }
}
</style>
