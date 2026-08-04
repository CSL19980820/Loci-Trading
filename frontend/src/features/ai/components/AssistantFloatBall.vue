<script setup lang="ts">
import { ChatDotRound } from '@element-plus/icons-vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps<{ open: boolean; busy?: boolean; unavailable?: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const storageKey = 'loci.assistant.ball.pos'
const position = ref({ right: 24, bottom: 88 })
const dragging = ref(false)
let pointerStart: { x: number; y: number; right: number; bottom: number } | null = null
let ignoreNextClick = false

const style = computed(() => ({ right: `${position.value.right}px`, bottom: `${position.value.bottom}px` }))

/** Mobile bottom-nav clearance in px; 0 when bottom nav is hidden (>768). */
function navClearancePx(): number {
  if (typeof window === 'undefined' || window.innerWidth > 768) return 0
  const root = document.documentElement
  const fs = Number.parseFloat(getComputedStyle(root).fontSize) || 16
  const raw = getComputedStyle(root).getPropertyValue('--mobile-nav-h').trim() || '3.5rem'
  const nav = raw.endsWith('rem') ? Number.parseFloat(raw) * fs : Number.parseFloat(raw) || 3.5 * fs
  return Math.round(nav + fs * 0.75)
}

function bottomFloor(): number {
  return 12 + navClearancePx()
}

function defaultBottom(): number {
  if (window.innerWidth > 768) return 88
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
  <el-tooltip :content="unavailable ? '请先在运维中配置模型' : '打开 Loci 助手（Ctrl+/）'">
    <el-button
      class="assistant-float-ball"
      :class="{ 'is-busy': busy, 'is-open': open, 'is-unavailable': unavailable }"
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
      <el-icon><ChatDotRound /></el-icon>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
.assistant-float-ball { position: fixed; z-index: 3200; width: 52px; height: 52px; margin: 0; border-color: color-mix(in srgb, #fff 18%, transparent); background: color-mix(in srgb, var(--ink) 92%, var(--seal) 8%); color: var(--paper); box-shadow: 0 8px 24px color-mix(in srgb, var(--ink) 22%, transparent); touch-action: none; }
.assistant-float-ball:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 3px; }
.assistant-float-ball.is-open { width: 40px; height: 40px; }
.assistant-float-ball.is-unavailable { opacity: .55; }
.assistant-float-ball.is-busy::after { position: absolute; inset: -4px; border: 2px solid var(--el-color-primary); border-radius: 50%; content: ''; animation: breathe 1.6s ease-in-out infinite; }
@keyframes breathe { 50% { opacity: .35; transform: scale(1.12); } }
@media (prefers-reduced-motion: no-preference) { .assistant-float-ball:hover { transform: scale(1.04); } }
@media (prefers-reduced-motion: reduce) { .assistant-float-ball.is-busy::after { animation: none; opacity: .7; } }
</style>
