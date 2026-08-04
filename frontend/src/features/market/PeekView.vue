<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { getLiveTape, type LiveTapeItem } from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'

import { shouldShowGhost } from './composables/peekChrome'

type PeekPhase = 'free' | 'collapsed'
type PeekEdge = 'left' | 'right' | 'top' | 'bottom'

const indices = ref<LiveTapeItem[]>([])
const positions = ref<LiveTapeItem[]>([])
const asOf = ref('')
const error = ref('')
const phase = ref<PeekPhase>('free')
const edge = ref<PeekEdge>('right')
const viewportW = ref(typeof window !== 'undefined' ? window.innerWidth : 340)
const viewportH = ref(typeof window !== 'undefined' ? window.innerHeight : 340)
let lifecycleGeneration = 0

const showGhost = computed(() =>
  shouldShowGhost(phase.value, viewportW.value, viewportH.value),
)

function paintChrome(): void {
  // 透明壳只在真探头尺寸；phase/几何不一致时保持不透明 free，避免 340² 白块。
  document.documentElement.dataset.peekPhase = showGhost.value ? 'collapsed' : 'free'
  document.documentElement.dataset.peekEdge = edge.value
}

paintChrome()

function tone(pct: number | null | undefined): string {
  if (pct == null) return ''
  if (pct > 0) return 'is-up'
  if (pct < 0) return 'is-down'
  return 'is-flat'
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function fmtPctShort(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(1)}%`
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  return n >= 1000 ? n.toFixed(2) : n.toFixed(2)
}

function fmtCost(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value)) || Number(value) <= 0) return '—'
  return Number(value).toFixed(2)
}

const clock = computed(() => {
  const raw = asOf.value
  if (!raw) return '连接中…'
  const part = raw.split(' ')[1]
  return part ? part.slice(0, 8) : raw
})

/** 市值加权今日涨跌（与托盘「仓」同口径；不用成本浮盈） */
const bagPct = computed((): number | null => {
  const rows = positions.value.filter((p) => p.ok && p.pct != null)
  if (!rows.length) return null
  let weighted = 0
  let weight = 0
  for (const p of rows) {
    const pct = Number(p.pct)
    const mv =
      p.market_value ??
      (p.price != null && p.shares ? Number(p.price) * Number(p.shares) : 0)
    if (mv > 0) {
      weighted += pct * mv
      weight += mv
    }
  }
  if (weight > 0) return weighted / weight
  return rows.reduce((s, p) => s + Number(p.pct), 0) / rows.length
})

const sortedPositions = computed(() =>
  [...positions.value].sort((a, b) => {
    const ap = a.pct == null ? 0 : Number(a.pct)
    const bp = b.pct == null ? 0 : Number(b.pct)
    return ap - bp
  }),
)

/** 行情轮询：宿主 phase=collapsed 即停；展示层用 showGhost（含视口守卫）。 */
const hostCollapsed = computed(() => phase.value === 'collapsed')

type PeekApi = {
  peek_pointer_enter?: () => void | Promise<void>
  peek_pointer_leave?: () => void | Promise<void>
  peek_close?: () => void | Promise<void>
  peek_get_state?: () => Promise<{ phase?: string; edge?: string }> | { phase?: string; edge?: string }
}

function peekApi(): PeekApi | undefined {
  return (window as unknown as { pywebview?: { api?: PeekApi } }).pywebview?.api
}

function measureViewport(): void {
  viewportW.value = window.innerWidth
  viewportH.value = window.innerHeight
  paintChrome()
}

function applyPhase(nextPhase: string, nextEdge: string): void {
  if (nextPhase === 'free' || nextPhase === 'collapsed') {
    phase.value = nextPhase
  }
  if (nextEdge === 'left' || nextEdge === 'right' || nextEdge === 'top' || nextEdge === 'bottom') {
    edge.value = nextEdge
  }
  measureViewport()
  if (showGhost.value) {
    document.title = 'Loci'
  }
}

function onPointerEnter(): void {
  void peekApi()?.peek_pointer_enter?.()
}

function onPointerLeave(): void {
  void peekApi()?.peek_pointer_leave?.()
}

function onClose(): void {
  void peekApi()?.peek_close?.()
}

async function syncStateFromHost(): Promise<void> {
  try {
    const state = await peekApi()?.peek_get_state?.()
    if (state?.phase || state?.edge) {
      applyPhase(String(state.phase || phase.value), String(state.edge || edge.value))
    }
  } catch {
    /* 浏览器打开 /peek 时无 bridge */
  }
}

/** 宿主 reveal 常早于 Vue 挂载；evaluate_js 会空推，需短窗重同步避免卡在透明缩进壳。 */
const PHASE_RESYNC_MS = [120, 400, 1000] as const
const phaseResyncTimers: number[] = []

function schedulePhaseResync(): void {
  const generation = lifecycleGeneration
  void syncStateFromHost()
  for (const ms of PHASE_RESYNC_MS) {
    phaseResyncTimers.push(
      window.setTimeout(() => {
        if (generation !== lifecycleGeneration) return
        void syncStateFromHost()
      }, ms),
    )
  }
}

function clearPhaseResync(): void {
  for (const id of phaseResyncTimers) window.clearTimeout(id)
  phaseResyncTimers.length = 0
}

async function tick(): Promise<void> {
  const generation = lifecycleGeneration
  if (hostCollapsed.value) return
  try {
    const tape = await getLiveTape()
    if (generation !== lifecycleGeneration || hostCollapsed.value) return
    indices.value = tape.indices || []
    positions.value = tape.positions || []
    asOf.value = tape.as_of || ''
    error.value = tape.error || ''
    const bag = bagPct.value
    document.title =
      bag != null ? `仓${fmtPctShort(bag)} · Loci` : tape.title || 'Loci · 行情'
  } catch (caught: unknown) {
    if (generation !== lifecycleGeneration) return
    error.value = caught instanceof Error ? caught.message : '行情失败'
  }
}

const { refreshOnce } = useLivePolling({ intervalMs: 4000, tick })

// 宿主从 collapsed → free，或视口从探头放大后，立刻补拉行情
watch(showGhost, (now, prev) => {
  if (prev && !now) void refreshOnce()
})

watch(hostCollapsed, (now, prev) => {
  if (prev && !now) void refreshOnce()
})

onMounted(() => {
  ;(window as unknown as { __lociPeekSetPhase?: typeof applyPhase }).__lociPeekSetPhase = applyPhase
  measureViewport()
  window.addEventListener('resize', measureViewport)
  schedulePhaseResync()
  void refreshOnce()
  document.getElementById('boot-splash')?.remove()
})

onUnmounted(() => {
  lifecycleGeneration += 1
  clearPhaseResync()
  window.removeEventListener('resize', measureViewport)
  const w = window as unknown as { __lociPeekSetPhase?: typeof applyPhase }
  if (w.__lociPeekSetPhase === applyPhase) delete w.__lociPeekSetPhase
})
</script>

<template>
  <!-- 缩进：矢量圆标嵌边（避免 PNG 缩放毛边），零行情信息 -->
  <main
    v-if="showGhost"
    class="peek peek--ghost"
    :class="`peek--edge-${edge}`"
    aria-label="行情"
    @mouseenter="onPointerEnter"
    @mouseleave="onPointerLeave"
  >
    <div class="icon-shift">
      <svg
        class="app-badge"
        viewBox="0 0 32 32"
        width="28"
        height="28"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="16" cy="16" r="16" fill="#c41e3a" />
        <path fill="#fff" d="M8.4 7.8h4.1v11.2h6.4v3.9H8.4z" />
        <path
          d="M23.1 10.5a7.1 7.1 0 1 0 0 11"
          fill="none"
          stroke="#fff"
          stroke-width="3.5"
          stroke-linecap="butt"
        />
      </svg>
    </div>
  </main>

  <main
    v-else
    class="peek"
    @mouseenter="onPointerEnter"
    @mouseleave="onPointerLeave"
  >
    <header class="peek-chrome pywebview-drag-region">
      <div class="peek-head">
        <div class="peek-head__left">
          <span class="peek-kicker">盘面</span>
          <span class="peek-clock">{{ clock }}</span>
        </div>
        <div class="peek-bag" :class="tone(bagPct)">
          <span class="peek-bag__label">仓</span>
          <strong>{{ fmtPct(bagPct) }}</strong>
        </div>
        <el-button
          class="peek-close"
          text
          circle
          size="small"
          aria-label="隐藏行情窗"
          @click.stop="onClose"
        >
          ×
        </el-button>
      </div>
    </header>

    <section class="peek-rail" aria-label="指数">
      <article
        v-for="item in indices"
        :key="item.code"
        class="peek-rail__cell"
        :class="tone(item.pct)"
      >
        <span class="label">{{ item.label }}</span>
        <strong class="px">{{ fmtPrice(item.price) }}</strong>
        <b>{{ fmtPct(item.pct) }}</b>
      </article>
    </section>

    <section v-if="sortedPositions.length" class="peek-pos">
      <div class="peek-pos__head">
        <h2>持仓 · 今日</h2>
        <span class="peek-pos__cols" aria-hidden="true">
          <em>现价</em>
          <em>成本</em>
          <em>涨跌</em>
        </span>
      </div>
      <div
        v-for="item in sortedPositions"
        :key="item.code"
        class="peek-row"
        :class="tone(item.pct)"
      >
        <span class="name">{{ item.name || item.label }}</span>
        <span class="nums">
          <strong class="px">{{ fmtPrice(item.price) }}</strong>
          <span class="cost">{{ fmtCost(item.cost) }}</span>
          <b>{{ fmtPct(item.pct) }}</b>
        </span>
      </div>
    </section>
    <p v-else-if="!error" class="peek-empty">空仓</p>

    <p v-if="error" class="peek-err">{{ error }}</p>
  </main>
</template>

<style scoped>
.peek {
  box-sizing: border-box;
  height: 100%;
  min-height: 100dvh;
  padding: 0.55rem 0.7rem 0.65rem;
  background: var(--paper, #eef2f6);
  color: var(--ink);
  overflow: hidden;
}
.peek-chrome {
  margin: -0.55rem -0.7rem 0.45rem;
  padding: 0.45rem 0.7rem 0.35rem;
  cursor: move;
}
.peek-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 0.5rem;
}
.peek-head__left {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
}
.peek-kicker {
  font: 650 0.72rem/1 var(--font-sans, system-ui);
  color: var(--ink);
  letter-spacing: 0.04em;
}
.peek-clock {
  color: var(--mist);
  font: 500 0.7rem/1 var(--mono);
  font-variant-numeric: tabular-nums;
}
.peek-bag {
  display: flex;
  align-items: baseline;
  gap: 0.28rem;
  margin-left: auto;
}
.peek-bag__label {
  color: var(--mist);
  font-size: 0.72rem;
  font-weight: 600;
}
.peek-bag strong {
  font: 700 1.2rem/1 var(--mono);
  font-variant-numeric: tabular-nums;
}
.peek-close {
  flex: 0 0 auto;
  font-size: 1rem;
  line-height: 1;
  color: var(--mist);
  cursor: pointer;
}
.peek-rail {
  display: flex;
  border: 1px solid var(--rule);
  background: color-mix(in srgb, var(--paper, #fff) 70%, #fff);
  overflow: hidden;
}
.peek-rail__cell {
  flex: 1;
  min-width: 0;
  padding: 0.35rem 0.25rem;
  text-align: center;
  display: grid;
  gap: 0.12rem;
  border-left: 1px solid var(--rule);
}
.peek-rail__cell:first-child {
  border-left: none;
}
.peek-rail__cell .label {
  color: var(--mist);
  font-size: 0.68rem;
  font-weight: 500;
}
.peek-rail__cell .px {
  font: 600 0.78rem/1 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.peek-rail__cell b {
  font: 650 0.78rem/1 var(--mono);
  font-variant-numeric: tabular-nums;
}
.peek-pos {
  margin-top: 0.5rem;
}
.peek-pos__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.4rem;
  margin-bottom: 0.15rem;
}
.peek-pos h2 {
  margin: 0;
  font-size: 0.7rem;
  color: var(--mist);
  font-weight: 600;
}
.peek-pos__cols {
  display: grid;
  grid-template-columns: 3.6rem 3.4rem 3.6rem;
  gap: 0.25rem;
  color: var(--mist);
  font-size: 0.62rem;
  font-weight: 500;
  text-align: right;
}
.peek-pos__cols em {
  font-style: normal;
}
.peek-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.45rem;
  padding: 0.22rem 0;
  border-bottom: 1px solid var(--rule);
  font-size: 0.82rem;
}
.peek-row .name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.peek-row .nums {
  display: grid;
  grid-template-columns: 3.6rem 3.4rem 3.6rem;
  gap: 0.25rem;
  flex: 0 0 auto;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
}
.peek-row .px {
  font-weight: 650;
  color: var(--ink);
}
.peek-row .cost {
  font-weight: 500;
  color: var(--mist);
  font-size: 0.78rem;
}
.peek-row b {
  font-weight: 650;
}
.peek-empty {
  margin-top: 0.85rem;
  color: var(--mist);
  font-size: 0.85rem;
}
.is-up b,
.is-up strong {
  color: var(--up);
}
.is-down b,
.is-down strong {
  color: var(--down);
}
.is-flat b,
.is-flat strong {
  color: var(--mist);
}
.peek-err {
  margin-top: 0.8rem;
  color: var(--seal-ink);
  font-size: 0.85rem;
}

/* —— 贴边探头：矢量圆标（无位图毛边） —— */
.peek--ghost {
  margin: 0;
  padding: 0;
  min-height: 100dvh;
  width: 100%;
  height: 100%;
  background: transparent;
  overflow: hidden;
  cursor: pointer;
}
.icon-shift {
  width: 2.25rem;
  height: 2.25rem;
}
.peek--edge-left .icon-shift {
  margin-left: -0.25rem;
}
.peek--edge-right .icon-shift {
  margin-left: 0;
}
.peek--edge-top .icon-shift {
  margin-top: -0.25rem;
}
.peek--edge-bottom .icon-shift {
  margin-top: -0.25rem;
}
.app-badge {
  width: 2.25rem;
  height: 2.25rem;
  display: block;
  pointer-events: none;
  user-select: none;
  shape-rendering: geometricPrecision;
}
</style>

<!-- 缩进态透明嵌边；展开态强制不透明，避免竞态残留空白壳。探头窗取消 body min-width。 -->
<style>
html[data-peek-phase] body {
  min-width: 0;
}
html[data-peek-phase='collapsed'],
html[data-peek-phase='collapsed'] body,
html[data-peek-phase='collapsed'] #app {
  background: transparent !important;
}
html[data-peek-phase='free'],
html[data-peek-phase='free'] body,
html[data-peek-phase='free'] #app {
  background: #eef2f6 !important;
}
</style>
