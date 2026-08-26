<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

defineProps<{ open: boolean; busy?: boolean; unavailable?: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const storageKey = 'loci.assistant.ball.pos'
const position = ref({ right: 24, bottom: 88 })
const dragging = ref(false)
let pointerStart: { x: number; y: number; right: number; bottom: number } | null = null
let ignoreNextClick = false

const style = computed(() => ({ right: `${position.value.right}px`, bottom: `${position.value.bottom}px` }))

/**
 * 底栏 + 「记一笔」FAB 的避让高度；两者都在 ≤980px 出现（与 AppSidebar 隐藏点一致）。
 * 断点此前写的 768，导致 769–980px 时浮球以为自己在桌面，落点正好压住 FAB，
 * 而浮球 z-index 3200 远高于 FAB 的 40，FAB 会被盖住且点不到。
 */
function navClearancePx(): number {
  if (typeof window === 'undefined' || window.innerWidth > 980) return 0
  const root = document.documentElement
  const fs = Number.parseFloat(getComputedStyle(root).fontSize) || 16
  const raw = getComputedStyle(root).getPropertyValue('--mobile-nav-h').trim() || '3.5rem'
  const nav = raw.endsWith('rem') ? Number.parseFloat(raw) * fs : Number.parseFloat(raw) || 3.5 * fs
  return Math.round(nav + fs * 0.75)
}

/** 下限要越过「记一笔」FAB（约 40px + 间距），否则用户往下一拖就把它盖死 */
function fabClearancePx(): number {
  if (typeof window === 'undefined' || window.innerWidth > 980) return 0
  return 52
}

function bottomFloor(): number {
  return 12 + navClearancePx() + fabClearancePx()
}

function defaultBottom(): number {
  if (window.innerWidth > 980) return 88
  const fs = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  return Math.round(navClearancePx() + 3.5 * fs)
}

function clamp(): void {
  const minBottom = bottomFloor()
  position.value.right = Math.max(12, Math.min(position.value.right, Math.max(12, window.innerWidth - 52)))
  position.value.bottom = Math.max(minBottom, Math.min(position.value.bottom, Math.max(minBottom + 60, window.innerHeight - 52)))
}

function persist(): void {
  localStorage.setItem(storageKey, JSON.stringify(position.value))
}

function onPointerDown(event: PointerEvent): void {
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  pointerStart = { x: event.clientX, y: event.clientY, right: position.value.right, bottom: position.value.bottom }
  dragging.value = false
}

function onPointerMove(event: PointerEvent): void {
  if (!pointerStart) return
  const dx = event.clientX - pointerStart.x
  const dy = event.clientY - pointerStart.y
  if (Math.hypot(dx, dy) > 6) dragging.value = true
  if (!dragging.value) return
  position.value = { right: pointerStart.right - dx, bottom: pointerStart.bottom - dy }
  clamp()
}

function onPointerUp(): void {
  if (!pointerStart) return
  const wasDragging = dragging.value
  pointerStart = null
  dragging.value = false
  if (!wasDragging) return
  persist()
  ignoreNextClick = true
  window.setTimeout(() => { ignoreNextClick = false })
}

function onPointerCancel(): void {
  pointerStart = null
  dragging.value = false
}

function onClick(): void {
  if (ignoreNextClick) {
    ignoreNextClick = false
    return
  }
  emit('toggle')
}

function onResize(): void { clamp() }

onMounted(() => {
  const saved = localStorage.getItem(storageKey)
  if (saved) {
    try { position.value = { ...position.value, ...JSON.parse(saved) } } catch { /* Ignore an invalid persisted position. */ }
  } else {
    position.value.bottom = defaultBottom()
  }
  clamp()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<template>
  <el-tooltip
    :content="unavailable ? '请先在运维中配置模型' : open ? '关闭 Loci 助手' : '打开 Loci 助手（Ctrl+/）'"
  >
    <el-button
      class="assistant-float-ball"
      :class="{ 'is-busy': busy, 'is-open': open, 'is-unavailable': unavailable, 'is-dragging': dragging }"
      :style="style"
      circle
      :aria-label="open ? '关闭 Loci 助手' : '打开 Loci 助手'"
      :aria-expanded="open"
      :aria-busy="busy"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @click="onClick"
    >
      <!-- Ink Ribbon Disc: dark plate + light ribbon knot + seal locus (open → X) -->
      <svg class="ball-mark" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
        <g v-if="open" class="ball-mark__close" stroke="currentColor" stroke-width="2.6" stroke-linecap="round">
          <line x1="17" y1="17" x2="31" y2="31" />
          <line x1="31" y1="17" x2="17" y2="31" />
        </g>
        <g v-else class="ball-mark__ribbon" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
          <path
            class="ball-mark__loop"
            stroke-width="2.35"
            d="M16.5 28.5 C17.8 18.5 24.5 15 29.5 19.5 C34.8 24.2 32.2 33.5 24.5 33.5 C19.5 33.5 16.2 30.8 16.5 28.5 Z"
          />
          <path class="ball-mark__sweep" stroke-width="1.85" opacity="0.72" d="M19.5 18.5 C24.5 22 28.2 26.8 26.8 32.2" />
          <circle class="ball-mark__locus" cx="24" cy="24" r="2.15" fill="var(--seal)" stroke="none" />
        </g>
      </svg>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
/* EP .is-circle defaults to width:32px — must beat that or the ball becomes an ellipse. */
.assistant-float-ball.el-button.is-circle {
  --ball-face: var(--ai-disc-face);
  --ball-ribbon: var(--ai-disc-ribbon);
  --el-button-size: 52px;
  position: fixed;
  z-index: 3200;
  box-sizing: border-box;
  width: 52px;
  height: 52px;
  min-width: 52px;
  min-height: 52px;
  padding: 0;
  margin: 0;
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  border: 1px solid var(--ai-disc-edge);
  background: var(--ball-face);
  color: var(--ball-ribbon);
  box-shadow:
    0 1px 0 color-mix(in srgb, #fff 10%, transparent) inset,
    0 10px 28px color-mix(in srgb, #000 28%, transparent);
  touch-action: none;
  transition:
    width 0.18s ease,
    height 0.18s ease,
    min-width 0.18s ease,
    min-height 0.18s ease,
    transform 0.18s ease,
    background 0.18s ease,
    border-color 0.18s ease,
    opacity 0.18s ease;
}

.assistant-float-ball :deep(span) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  margin: 0;
}

.ball-mark {
  width: 26px;
  height: 26px;
  display: block;
  flex-shrink: 0;
}

.assistant-float-ball:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: 3px;
}

.assistant-float-ball.el-button.is-circle.is-open {
  --el-button-size: 40px;
  width: 40px;
  height: 40px;
  min-width: 40px;
  min-height: 40px;
}

.assistant-float-ball.is-open .ball-mark {
  width: 20px;
  height: 20px;
}

.assistant-float-ball.is-unavailable {
  --ball-face: #2a3038;
  --ball-ribbon: #7a8494;
  border-color: color-mix(in srgb, #fff 8%, transparent);
  box-shadow: 0 6px 18px color-mix(in srgb, #000 18%, transparent);
}

.assistant-float-ball.is-unavailable .ball-mark__locus {
  fill: #6b7280;
}

.assistant-float-ball.is-busy::after {
  position: absolute;
  inset: -5px;
  border: 2px dashed var(--seal);
  border-radius: 50%;
  content: '';
  opacity: 0.85;
  pointer-events: none;
  animation: orbit-spin 1.35s linear infinite;
}

.assistant-float-ball.is-dragging {
  cursor: grabbing;
  transition: none;
}

@media (prefers-reduced-motion: no-preference) {
  .assistant-float-ball:hover:not(.is-dragging) {
    transform: scale(1.05);
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-float-ball,
  .assistant-float-ball.is-open {
    transition: none;
  }

  .assistant-float-ball.is-busy::after {
    animation: none;
    opacity: 0.7;
    border-style: solid;
  }
}

@keyframes orbit-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
