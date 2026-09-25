<script setup lang="ts">
import { ChevronDown, CircleCheck, CircleAlert, Lightbulb, Sparkles } from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Button } from '@/shared/components/ui/button'

/** 思考阶段的状态；本地实现自带，不再依赖第三方 Thinking 类型包。 */
type ThinkingStatus = 'start' | 'thinking' | 'end' | 'error' | 'cancel'

const props = defineProps<{
  content: string
  streaming?: boolean
  /** Collapse when thinking phase ends (tools / answer / settled). */
  autoCollapse?: boolean
  /** A real execution phase exists, but the provider has not emitted reasoning. */
  pending?: boolean
  label?: string
  interrupted?: boolean
}>()

const expanded = ref(true)
const rootRef = ref<HTMLElement | null>(null)

const status = computed<ThinkingStatus>(() => {
  if (props.interrupted) return 'error'
  if (!props.content.trim()) return 'start'
  return props.streaming ? 'thinking' : 'end'
})

/** 与旧 Thinking 的默认文案一致：开始思考 / 思考中... / 思考完成 */
const label = computed(() => {
  if (props.label) return props.label
  if (status.value === 'thinking') return '思考中...'
  if (status.value === 'end') return '思考完成'
  return '开始思考'
})

watch(
  () => [props.autoCollapse, props.streaming, props.content] as const,
  ([auto, streaming]) => {
    if (!props.content.trim()) return
    // 思考中保持展开；一旦进入收起条件（status→end + autoCollapse）立刻折起
    if (streaming) {
      expanded.value = true
      return
    }
    if (auto) expanded.value = false
  },
  { immediate: true },
)

/** 思考正文区域内跟滚，长推理时始终看见最新句。 */
watch(
  () => [props.content, props.streaming, expanded.value] as const,
  async ([, streaming, open]) => {
    if (!streaming || !open) return
    await nextTick()
    const pre = rootRef.value?.querySelector('.assistant-thinking__content') as HTMLElement | null
    if (pre) pre.scrollTop = pre.scrollHeight
  },
  { flush: 'post' },
)
</script>

<template>
  <div
    v-if="content.trim() || pending"
    ref="rootRef"
    class="assistant-thinking"
    data-testid="assistant-thinking"
    :data-status="status"
    :data-expanded="String(expanded)"
    aria-label="思考过程"
  >
    <Collapsible v-model:open="expanded" class="assistant-thinking__box" :class="{ 'is-live': status === 'thinking' }">
      <CollapsibleTrigger as-child><Button access="read" variant="ghost" class="assistant-thinking__trigger" :disabled="!content.trim()">
        <span class="assistant-thinking__icon" aria-hidden="true">
          <Sparkles v-if="status === 'thinking' || pending" class="assistant-thinking__spark" />
          <CircleAlert v-else-if="interrupted" />
          <CircleCheck v-else-if="status === 'end'" />
          <Lightbulb v-else />
        </span>
        <span class="assistant-thinking__label" :class="{ 'is-shimmer': status === 'thinking' }">{{ label }}</span>
        <span v-if="status === 'end'" class="assistant-thinking__hint">{{ expanded ? '收起' : '展开' }}</span>
        <ChevronDown
          v-if="content.trim()"
          class="assistant-thinking__arrow"
          :class="{ 'is-expanded': expanded }"
          aria-hidden="true"
        />
      </Button></CollapsibleTrigger>
      <CollapsibleContent v-if="content.trim()">
        <pre class="assistant-thinking__content">{{ content }}</pre>
      </CollapsibleContent>
    </Collapsible>
  </div>
</template>

<style scoped>
.assistant-thinking {
  width: 100%;
  min-width: 0;
}

.assistant-thinking__box {
  width: 100%;
  min-width: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: transparent;
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease);
}

.assistant-thinking__box[data-state='open'] {
  border-color: var(--border-subtle);
  background: var(--surface-sunken);
}

.assistant-thinking__box.is-live {
  border-color: var(--seal-border);
}

.assistant-thinking__trigger {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-width: 0;
  height: auto;
  min-height: 32px;
  padding: 6px 8px;
  justify-content: flex-start;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 500;
  text-align: left;
  cursor: pointer;
}

.assistant-thinking__trigger:hover {
  color: var(--text-primary);
}

.assistant-thinking__trigger:disabled { opacity:1; cursor:default; }

.assistant-thinking__trigger:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.assistant-thinking__icon {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  color: var(--text-tertiary);
}

.assistant-thinking__icon :deep(svg) {
  width: 14px;
  height: 14px;
}

.assistant-thinking__spark {
  color: var(--seal);
  animation: assistant-thinking-twinkle 1.6s ease-in-out infinite;
}

.assistant-thinking__label {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 流式时文字走一层从左到右的高光（shimmer） */
.assistant-thinking__label.is-shimmer {
  background: linear-gradient(
    90deg,
    var(--text-tertiary) 0%,
    var(--text-primary) 45%,
    var(--text-tertiary) 90%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: assistant-thinking-shimmer 1.8s linear infinite;
}

.assistant-thinking__hint {
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.assistant-thinking__arrow {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transition: transform var(--dur-fast) var(--ease);
}

.assistant-thinking__hint + .assistant-thinking__arrow {
  margin-left: 0;
}

.assistant-thinking__label + .assistant-thinking__arrow {
  margin-left: auto;
}

.assistant-thinking__arrow.is-expanded {
  transform: rotate(180deg);
}

/* 思考正文：限高 + 内滚，避免把结论/工具顶出视口 */
.assistant-thinking__content {
  margin: 0;
  max-height: 12rem;
  padding: 0 var(--gap-3) var(--gap-3);
  color: var(--text-secondary);
  font-family: var(--font);
  font-size: var(--fs-aux);
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow-y: auto;
  scrollbar-width: thin;
}

@keyframes assistant-thinking-shimmer {
  from {
    background-position: 110% 0;
  }
  to {
    background-position: -110% 0;
  }
}

@keyframes assistant-thinking-twinkle {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.55;
    transform: scale(0.9);
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-thinking__spark,
  .assistant-thinking__label.is-shimmer {
    animation: none;
  }

  .assistant-thinking__label.is-shimmer {
    color: var(--text-secondary);
    background: none;
  }

  .assistant-thinking__arrow {
    transition: none;
  }
}
</style>
