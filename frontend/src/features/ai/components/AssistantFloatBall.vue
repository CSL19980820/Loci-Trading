<script setup lang="ts">
import { ChatDotRound, Close } from '@element-plus/icons-vue'
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
 * 断点此前写的 768，导致 769–980px 时浮球以为自己在桌面，落点正好压住 FAB，
 * 而浮球 z-index（--z-assistant-ball）远高于 FAB（--z-record-fab），FAB 会被盖住且点不到。
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
      <el-icon class="ball-mark" aria-hidden="true"><Close v-if="open" /><ChatDotRound v-else /></el-icon>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
/* 尺寸与脚本中的拖拽边界保持一致；浮球使用公共浮层阴影。 */
.assistant-float-ball.el-button.is-circle {
  --ball-size: 52px;
  position: fixed; z-index: var(--z-assistant-ball); display: grid; place-items: center; width: var(--ball-size); height: var(--ball-size); min-width: var(--ball-size); min-height: var(--ball-size); margin: 0; padding: 0; border: 1px solid var(--seal-border); border-radius: 50%; background: var(--surface-raised); color: var(--seal-ink); box-shadow: var(--shadow-hover); touch-action: none; transition: border-color var(--dur-fast), background var(--dur-fast);
}
.assistant-float-ball.el-button.is-circle.is-open { --ball-size: 40px; }
.assistant-float-ball.el-button.is-circle:hover { background: var(--surface-hover); border-color: var(--seal); }
.assistant-float-ball :deep(> span) { display: flex; align-items: center; justify-content: center; }
.assistant-float-ball .ball-mark { font-size: var(--fs-hero); }
.assistant-float-ball:focus-visible { outline: 2px solid var(--seal); outline-offset: 3px; }
.assistant-float-ball.el-button.is-unavailable { color: var(--mist); border-color: var(--rule); background: var(--surface-sunken); }
.assistant-float-ball.is-busy::after { position: absolute; inset: calc(-1 * var(--gap-1)); border: 1px dashed var(--seal); border-radius: 50%; content: ''; pointer-events: none; animation: assistant-orbit 2s linear infinite; }
.assistant-float-ball.is-dragging { cursor: grabbing; transition: none; }
@keyframes assistant-orbit { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .assistant-float-ball.el-button.is-circle { transition: none; } .assistant-float-ball.is-busy::after { animation: none; border-style: solid; } }
</style>
