<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

import { getLiveTape, type LiveTapeItem } from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import { price as fmtPrice, pct as fmtPct } from '@/shared/lib/format'

import { shouldShowGhost } from './composables/peekChrome'

type PeekPhase = 'free' | 'collapsed'
type PeekEdge = 'left' | 'right' | 'top' | 'bottom'

const indices = ref<LiveTapeItem[]>([])
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

const clock = computed(() => {
  const raw = asOf.value
  if (!raw) return error.value ? '报价未更新' : '等待行情…'
  const part = raw.split(' ')[1]
  return part ? part.slice(0, 8) : raw
})

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
    asOf.value = tape.as_of || ''
    error.value = tape.error || ''
    document.title = tape.title || 'Loci · 行情'
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
        <circle cx="16" cy="16" r="16" fill="currentColor" />
        <path class="app-badge__glyph" d="M8.4 7.8h4.1v11.2h6.4v3.9H8.4z" />
        <path
          class="app-badge__glyph"
          d="M23.1 10.5a7.1 7.1 0 1 0 0 11"
          fill="none"
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
        <el-button
          class="peek-close"
          text
          circle
          size="small"
          :icon="Close"
          aria-label="隐藏行情窗"
          @click.stop="onClose"
        />
      </div>
    </header>

    <section v-if="indices.length" class="peek-rail" aria-label="指数">
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
    <EmptyState
      v-else
      :description="error ? '行情暂不可用' : '暂无指数报价'"
      :reason="error ? '等待下一次更新' : '等待行情更新'"
    />

    <p v-if="error" class="peek-err" role="alert">{{ error }}</p>
  </main>
</template>

<style scoped>
/*
* 探头窗是独立 WebView，窗体就是视口：满屏高度只在下方非 scoped 块里对
* html/body/#app 声明一次。旧版在 .peek 与 .peek--ghost 各写一遍
* min-height:100dvh，两态各撑一次，缩进态还要靠 !important 掰回来。
*/
.peek {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  height: 100%;
  padding: var(--gap-1) var(--gap-2) var(--gap-2);
  background: var(--paper);
  color: var(--ink);
  overflow: hidden;
}
.peek-chrome {
  flex-shrink: 0;
  margin: calc(var(--gap-1) * -1) calc(var(--gap-2) * -1) 0;
  padding: var(--gap-1) var(--gap-2);
  cursor: move;
  border-bottom: 1px solid var(--rule);
  background: var(--sheet-alt);
}
.peek-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--gap-2);
}
.peek-head__left {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.peek-kicker {
  font: 700 var(--fs-kicker) / 1.2 var(--font-sans);
  color: var(--ink);
  letter-spacing: 0.04em;
}
.peek-clock {
  color: var(--mist);
  font: 500 var(--fs-kicker) / 1.2 var(--mono);
  font-variant-numeric: tabular-nums;
}
.peek-close {
  flex: 0 0 auto;
  margin-left: auto;
  font-size: var(--fs-title);
  line-height: 1;
  color: var(--mist);
  cursor: pointer;
}
.peek-rail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr));
  gap: 1px;
  flex: 0 1 auto;
  min-height: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--rule);
  overflow: auto;
  overscroll-behavior: contain;
}
.peek-rail__cell {
  flex: 1;
  min-width: 0;
  padding: var(--gap-2);
  text-align: left;
  display: grid;
  gap: var(--gap-1);
  background: var(--sheet);
}
.peek-rail__cell:first-child {
  border-left: none;
}
.peek-rail__cell .label {
  color: var(--mist);
  font-size: var(--fs-kicker);
  font-weight: 500;
}
/* D2：探头窗里最大的字是点位 */
.peek-rail__cell .px {
  font: 700 var(--fs-hero) / 1.15 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.peek-rail__cell b {
  font: 700 var(--fs-aux) / 1.15 var(--mono);
  font-variant-numeric: tabular-nums;
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
  margin: 0;
  color: var(--warn);
  font-size: var(--fs-aux);
  max-height: 4rem;
  overflow: auto;
  overflow-wrap: anywhere;
  flex-shrink: 0;
}
/* —— 贴边探头：矢量圆标（无位图毛边） —— */
.peek--ghost {
  display: block;
  margin: 0;
  padding: 0;
  gap: 0;
  height: 100%;
  background: transparent;
  overflow: hidden;
  cursor: pointer;
  /*
  * 品牌印记必须无论明暗都是「印章红盘 + 亮字」：字形跟着 --sheet 走会在
  * 夜盘翻成深色、直接消失在红盘里（参照 style.theme.css:117 的墨盘同款理由）。
  */
  --peek-badge-glyph: var(--on-primary);
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
.peek--edge-top .icon-shift,
.peek--edge-bottom .icon-shift {
  margin-top: -0.25rem;
}
.app-badge {
  width: 2.25rem;
  height: 2.25rem;
  display: block;
  color: var(--seal);
  pointer-events: none;
  user-select: none;
  shape-rendering: geometricPrecision;
}
.app-badge__glyph {
  fill: var(--peek-badge-glyph);
  stroke: var(--peek-badge-glyph);
}
</style>

<!-- 缩进态透明嵌边；展开态强制不透明，避免竞态残留空白壳。探头窗取消 body min-width。
     作用域：html[data-peek-phase] 只在 /peek 小窗存在，主应用无此属性，不会污染全局。 -->
<style>
/* 满屏高度的唯一声明处：scoped 里不再各态写一遍 min-height:100dvh */
html[data-peek-phase],
html[data-peek-phase] body,
html[data-peek-phase] #app {
  height: 100dvh;
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
  background: var(--paper) !important;
}
</style>
