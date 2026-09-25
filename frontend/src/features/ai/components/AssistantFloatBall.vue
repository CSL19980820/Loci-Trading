<script setup lang="ts">
import { MessageCircle as ChatDotRound, X as Close } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

import { computed, onMounted, onUnmounted, ref } from 'vue'

/**
 * 助手启动球（Intercom / ChatGPT launcher 一路）：48px 实心主色圆盘 + 白色图标 + 软投影；
 * 运行中外圈脉冲一圈；打开后缩成 40px 的关闭键。可拖拽，位置记在 localStorage。
 * 手机端默认落在底部导航之上（`--mobile-nav-h` + 16px），不压「记一笔」FAB。
 */
defineProps<{ open: boolean; busy?: boolean; unavailable?: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const storageKey = 'loci.assistant.ball.pos'
const position = ref({ right: 24, bottom: 88 })
const dragging = ref(false)
let pointerStart: { x: number; y: number; right: number; bottom: number } | null = null
let ignoreNextClick = false

const style = computed(() => ({ right: `${position.value.right}px`, bottom: `${position.value.bottom}px` }))

/** 底栏 + 「记一笔」FAB 的避让高度；两者都在 ≤980px 出现（与 AppSidebar 隐藏点一致）。 */
function navClearancePx(): number {
  if (typeof window === 'undefined' || window.innerWidth > 980) return 0
  const root = document.documentElement
  const fs = Number.parseFloat(getComputedStyle(root).fontSize) || 16
  const raw = getComputedStyle(root).getPropertyValue('--mobile-nav-h').trim() || '56px'
  const nav = raw.endsWith('rem') ? Number.parseFloat(raw) * fs : Number.parseFloat(raw) || 56
  return Math.round(nav + 16)
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
  return navClearancePx() + fabClearancePx() + 12
}

function clamp(): void {
  const minBottom = bottomFloor()
  position.value.right = Math.max(12, Math.min(position.value.right, Math.max(12, window.innerWidth - 60)))
  position.value.bottom = Math.max(minBottom, Math.min(position.value.bottom, Math.max(minBottom + 60, window.innerHeight - 60)))
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
  <Tooltip>
    <TooltipTrigger as-child>
      <Button access="read" variant="ghost"
        type="button"
        class="assistant-float-ball"
        :class="{ 'is-busy': busy, 'is-open': open, 'is-unavailable': unavailable, 'is-dragging': dragging }"
        :style="style"
        :aria-label="open ? '关闭 Loci 助手' : '打开 Loci 助手'"
        :aria-expanded="open"
        :aria-busy="busy"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerCancel"
        @click="onClick"
      >
        <span class="assistant-float-ball__mark" aria-hidden="true">
          <Close v-if="open" />
          <ChatDotRound v-else />
        </span>
        <span v-if="busy && !open" class="assistant-float-ball__pulse" aria-hidden="true" />
      </Button>
    </TooltipTrigger>
    <TooltipContent side="left">
      {{ unavailable ? '请先在设置里配置模型' : open ? '关闭 Loci 助手 · Esc' : '打开 Loci 助手 · Ctrl+/' }}
    </TooltipContent>
  </Tooltip>
</template>

<style scoped>
/* 尺寸与脚本中的拖拽边界保持一致 */
.assistant-float-ball {
  --ball-size: 48px;
  position: fixed;
  z-index: var(--z-assistant-ball);
  display: grid;
  place-items: center;
  width: var(--ball-size);
  height: var(--ball-size);
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background:
    linear-gradient(160deg, color-mix(in oklab, var(--seal) 92%, white), var(--seal) 60%, var(--seal-hover));
  color: var(--on-primary);
  box-shadow:
    var(--shadow-inset-highlight),
    0 10px 28px -8px color-mix(in oklab, var(--seal) 55%, transparent),
    var(--shadow-md);
  cursor: pointer;
  touch-action: none;
  transition:
    transform var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease),
    width var(--dur) var(--ease),
    height var(--dur) var(--ease),
    background var(--dur-fast) var(--ease);
}

.assistant-float-ball:hover {
  transform: translateY(-1px) scale(1.04);
  box-shadow:
    var(--shadow-inset-highlight),
    0 14px 32px -8px color-mix(in oklab, var(--seal) 60%, transparent),
    var(--shadow-lg);
}

.assistant-float-ball:active {
  transform: scale(0.97);
}

.assistant-float-ball:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 3px;
}

.assistant-float-ball__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.assistant-float-ball__mark :deep(svg) {
  width: 22px;
  height: 22px;
  stroke-width: 2;
}

/* 打开后面板自带关闭键，浮球退场（保留 DOM 供键盘 / 测试语义） */
.assistant-float-ball.is-open {
  --ball-size: 40px;
  background: var(--surface-raised);
  color: var(--text-secondary);
  box-shadow: var(--shadow-md), 0 0 0 1px var(--border-subtle);
  opacity: 0;
  pointer-events: none;
  transform: scale(0.8);
}

.assistant-float-ball.is-open .assistant-float-ball__mark :deep(svg) {
  width: 18px;
  height: 18px;
}

.assistant-float-ball.is-unavailable {
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  box-shadow: var(--shadow-sm), 0 0 0 1px var(--border-default);
}

/* 运行中：外圈脉冲 */
.assistant-float-ball__pulse {
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 2px solid color-mix(in oklab, var(--seal) 70%, transparent);
  animation: assistant-pulse 1.8s ease-out infinite;
  pointer-events: none;
}

.assistant-float-ball.is-dragging {
  cursor: grabbing;
  transition: none;
}

@keyframes assistant-pulse {
  0% {
    transform: scale(0.9);
    opacity: 0.9;
  }
  100% {
    transform: scale(1.45);
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-float-ball {
    transition: none;
  }

  .assistant-float-ball__pulse {
    animation: none;
    opacity: 0.7;
  }
}
</style>
