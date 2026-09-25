<script setup lang="ts">
/**
 * 战法足迹带：每条激活战法一根时间轨，选出日落成一个点。
 * 点击点位把日期抛给页面（档案页用它锚定 K 线）；实心 = 精选，环 = 观察，空心 = 落选，半透明 = 回填。
 */
import { computed, ref } from 'vue'
import { Radar } from '@lucide/vue'

import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

import type { FootprintLane, FootprintPick } from '../composables/useStrategyFootprints'

type RangeKey = '30' | '90' | '180' | '365'

const props = withDefaults(
  defineProps<{
    lanes: FootprintLane[]
    loading?: boolean
    focusDate?: string
    defaultRange?: RangeKey
    compact?: boolean
  }>(),
  { loading: false, focusDate: '', defaultRange: '90', compact: false },
)

const emit = defineEmits<{ pick: [date: string] }>()

const RANGES: PageTabItem[] = [
  { name: '30', label: '1月' },
  { name: '90', label: '3月' },
  { name: '180', label: '半年' },
  { name: '365', label: '1年' },
]

const DAY_MS = 86_400_000
const range = ref<string>(props.defaultRange)

function toTime(date: string): number {
  return Date.parse(`${date.slice(0, 10)}T00:00:00`)
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function shortDate(time: number, withYear: boolean): string {
  const d = new Date(time)
  return withYear
    ? `${String(d.getFullYear()).slice(2)}-${pad(d.getMonth() + 1)}`
    : `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const endTime = computed(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const latest = Math.max(
    today,
    ...props.lanes.map((lane) => (lane.latest ? toTime(lane.latest) : 0)).filter(Number.isFinite),
  )
  return latest
})
const spanMs = computed(() => Number(range.value) * DAY_MS)
const startTime = computed(() => endTime.value - spanMs.value)

type PlacedPick = FootprintPick & { left: number }

const rows = computed(() =>
  props.lanes.map((lane) => {
    const placed: PlacedPick[] = []
    for (const pick of lane.picks) {
      const time = toTime(pick.date)
      if (!Number.isFinite(time) || time < startTime.value || time > endTime.value) continue
      placed.push({ ...pick, left: ((time - startTime.value) / spanMs.value) * 100 })
    }
    // 落选先画、精选后画：同日重叠时精选在上层
    const order: Record<FootprintPick['tone'], number> = { drop: 0, watch: 1, pick: 2 }
    placed.sort((a, b) => order[a.tone] - order[b.tone])
    return { lane, placed }
  }),
)

const activeCount = computed(() => props.lanes.filter((lane) => lane.active).length)
const windowTotal = computed(() => rows.value.reduce((sum, row) => sum + row.placed.length, 0))
const rangeLabel = computed(() => RANGES.find((item) => item.name === range.value)?.label ?? '')

const ticks = computed(() => {
  const withYear = Number(range.value) > 180
  return [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    left: ratio * 100,
    text: shortDate(startTime.value + spanMs.value * ratio, withYear),
  }))
})

function latestText(lane: FootprintLane): string {
  return lane.latest ? lane.latest.slice(2) : '—'
}

function scoreText(value: number | null): string {
  if (value == null) return ''
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
</script>

<template>
  <section class="fp" :class="{ 'fp--compact': compact }" aria-label="战法足迹">
    <header class="fp__head">
      <span class="fp__title"><Radar aria-hidden="true" />战法足迹</span>
      <span class="fp__sum">
        <b>{{ activeCount }}</b> 激活
        <span class="fp__sep" aria-hidden="true">·</span>
        {{ rangeLabel }} <b>{{ windowTotal }}</b> 次
      </span>
      <span class="fp__legend" aria-hidden="true">
        <span><i class="fp__key is-pick" />精选</span>
        <span><i class="fp__key is-watch" />观察</span>
        <span><i class="fp__key is-drop" />落选</span>
      </span>
      <PageTabs v-model="range" :items="RANGES" variant="pill" dense :sticky="false" aria-label="足迹区间" class="fp__range" />
    </header>

    <div v-if="loading && !lanes.length" class="fp__skeleton" aria-hidden="true">
      <Skeleton v-for="n in 2" :key="n" class="h-5 w-full" />
    </div>
    <p v-else-if="!lanes.length" class="fp__empty">无选出记录</p>
    <template v-else>
      <ol class="fp__lanes">
        <li
          v-for="{ lane, placed } in rows"
          :key="lane.slug"
          class="fp__lane"
          :class="{ 'is-active': lane.active, 'is-quiet': !placed.length }"
          :aria-label="`${lane.name} ${placed.length} 次`"
        >
          <span class="fp__name" :title="lane.name">
            <span class="fp__led" aria-hidden="true" />
            <span class="fp__name-text">{{ lane.name }}</span>
          </span>
          <span class="fp__track">
            <Tooltip v-for="pick in placed" :key="pick.id" :delay-duration="80">
              <TooltipTrigger as-child>
                <button
                  type="button"
                  class="fp__dot"
                  :class="[`is-${pick.tone}`, { 'is-backfill': pick.backfill, 'is-focus': pick.date === focusDate }]"
                  :style="{ left: `${pick.left}%` }"
                  :aria-label="`${lane.name} ${pick.date} ${pick.decisionText}`"
                  @click="emit('pick', pick.date)"
                />
              </TooltipTrigger>
              <TooltipContent class="fp-tip" side="top">
                <span class="fp-tip__head">
                  <b>{{ pick.date }}</b>
                  <span class="fp-tip__tag" :class="`is-${pick.tone}`">{{ pick.decisionText }}</span>
                  <span v-if="scoreText(pick.score)" class="fp-tip__score">{{ scoreText(pick.score) }}</span>
                </span>
                <span class="fp-tip__lane">{{ lane.name }}<template v-if="pick.backfill"> · 回填</template></span>
                <span v-if="pick.reason" class="fp-tip__reason">{{ pick.reason }}</span>
              </TooltipContent>
            </Tooltip>
          </span>
          <span class="fp__meta">
            <b>{{ placed.length }}</b>
            <span class="fp__latest">{{ latestText(lane) }}</span>
          </span>
        </li>
      </ol>
      <div class="fp__axis" aria-hidden="true">
        <span />
        <span class="fp__ticks">
          <span v-for="tick in ticks" :key="tick.left" :style="{ left: `${tick.left}%` }">{{ tick.text }}</span>
        </span>
        <span />
      </div>
    </template>
  </section>
</template>

<style scoped>
.fp {
  --fp-name-w: minmax(96px, 168px);
  --fp-meta-w: 96px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 10px 14px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(180deg, color-mix(in oklab, var(--seal) 3%, transparent), transparent 60%),
    var(--surface);
}

.fp__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  min-width: 0;
}

.fp__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  letter-spacing: -0.005em;
}

.fp__title svg {
  width: 14px;
  height: 14px;
  color: var(--seal);
}

.fp__sum {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.fp__sum b {
  color: var(--text-primary);
  font-family: var(--mono);
  font-weight: 600;
}

.fp__sep {
  margin: 0 4px;
  color: var(--text-disabled);
}

.fp__legend {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.fp__legend > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.fp__key {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.fp__key.is-pick { background: var(--seal); }
.fp__key.is-watch { box-shadow: inset 0 0 0 2px var(--warn); }
.fp__key.is-drop { box-shadow: inset 0 0 0 1.5px var(--border-strong); }

.fp__range {
  margin: 0;
}

.fp__range :deep(.page-tabs__item) {
  height: 22px;
  padding: 0 8px;
  font-size: var(--fs-kicker);
}

.fp__skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 0;
}

.fp__empty {
  margin: 0;
  padding: 6px 0 4px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.fp__lanes {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 176px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.fp__lane,
.fp__axis {
  display: grid;
  grid-template-columns: var(--fp-name-w) minmax(0, 1fr) var(--fp-meta-w);
  align-items: center;
  gap: 14px;
}

.fp__lane {
  height: 28px;
  border-radius: var(--radius-sm);
}

.fp__lane:hover {
  background: color-mix(in oklab, var(--surface-hover) 60%, transparent);
}

.fp__name {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-left: 4px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.fp__name-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fp__led {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-strong);
}

.fp__lane.is-active .fp__name {
  color: var(--text-primary);
  font-weight: 550;
}

.fp__lane.is-active .fp__led {
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}

.fp__track {
  position: relative;
  height: 100%;
  margin-inline: 6px;
}

.fp__track::before {
  content: '';
  position: absolute;
  inset-inline: -6px;
  top: 50%;
  height: 1px;
  background: var(--border-subtle);
}

.fp__lane.is-active .fp__track::before {
  background: linear-gradient(90deg, var(--border-subtle), var(--border-default));
}

.fp__dot {
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  margin: -5px 0 0 -5px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: var(--seal);
  box-shadow: 0 0 0 2px var(--surface);
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}

.fp__dot:hover,
.fp__dot:focus-visible {
  z-index: 2;
  transform: scale(1.4);
  outline: none;
}

.fp__dot.is-watch {
  background: var(--surface);
  box-shadow: inset 0 0 0 2px var(--warn), 0 0 0 2px var(--surface);
}

.fp__dot.is-drop {
  width: 8px;
  height: 8px;
  margin: -4px 0 0 -4px;
  background: var(--surface);
  box-shadow: inset 0 0 0 1.5px var(--border-strong), 0 0 0 2px var(--surface);
}

.fp__dot.is-backfill {
  opacity: 0.5;
}

.fp__dot.is-focus {
  z-index: 3;
  box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--seal-border);
}

.fp__meta {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 8px;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.fp__meta b {
  color: var(--text-primary);
  font-size: var(--fs-aux);
  font-weight: 600;
}

.fp__lane.is-quiet .fp__meta b {
  color: var(--text-disabled);
}

.fp__ticks {
  position: relative;
  height: 12px;
  margin-inline: 6px;
}

.fp__ticks > span {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  color: var(--text-disabled);
  font: var(--fs-micro) / 1 var(--mono);
  white-space: nowrap;
}

.fp__ticks > span:first-child { transform: none; }
.fp__ticks > span:last-child { transform: translateX(-100%); }

.fp--compact {
  --fp-name-w: minmax(80px, 128px);
  --fp-meta-w: 76px;
  padding: 10px 12px 6px;
}

.fp--compact .fp__legend {
  display: none;
}

.fp--compact .fp__range {
  margin-left: auto;
}

@media (max-width: 767px) {
  .fp {
    --fp-name-w: 76px;
    --fp-meta-w: 30px;
    padding: 8px 10px 6px;
  }

  .fp__lane,
  .fp__axis {
    gap: 8px;
  }

  .fp__legend,
  .fp__latest {
    display: none;
  }

  .fp__range {
    margin-left: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .fp__dot {
    transition: none;
  }
}
</style>

<style>
.fp-tip {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-width: 18rem;
  white-space: normal;
}

.fp-tip__head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.fp-tip__tag {
  padding: 0 5px;
  border-radius: var(--radius-xs);
  font-family: var(--font);
  font-size: var(--fs-kicker);
  font-weight: 600;
  background: color-mix(in oklab, currentColor 14%, transparent);
}

.fp-tip__score {
  margin-left: auto;
  font-weight: 600;
}

.fp-tip__lane {
  opacity: 0.75;
  font-size: var(--fs-kicker);
}

.fp-tip__reason {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-height: 1.5;
  opacity: 0.9;
}
</style>
