<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import Thinking from 'vue-element-plus-x/es/Thinking/index.js'
import type { ThinkingStatus } from 'vue-element-plus-x/types/Thinking'

const props = defineProps<{
  content: string
  streaming?: boolean
  /** Collapse when thinking phase ends (tools / answer / settled). */
  autoCollapse?: boolean
}>()

const expanded = ref(true)
const rootRef = ref<HTMLElement | null>(null)

const status = computed<ThinkingStatus>(() => {
  if (!props.content.trim()) return 'start'
  return props.streaming ? 'thinking' : 'end'
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
    const pre = rootRef.value?.querySelector('.elx-thinking__content pre') as HTMLElement | null
    if (pre) pre.scrollTop = pre.scrollHeight
  },
  { flush: 'post' },
)
</script>

<template>
  <div
    v-if="content.trim()"
    ref="rootRef"
    class="assistant-thinking"
    data-testid="assistant-thinking"
  >
    <Thinking
      v-model="expanded"
      :content="content"
      :status="status"
      :auto-collapse="Boolean(autoCollapse)"
      button-width="100%"
      max-width="100%"
    />
  </div>
</template>

<style scoped>
.assistant-thinking {
  width: 100%;
  min-width: 0;
  margin-bottom: .15rem;
}
.assistant-thinking :deep(.elx-thinking) {
  width: 100%;
}
/* 思考流式时限高 + 内滚，避免把结论/工具顶出视口；隐藏滚动条仍可滚 */
.assistant-thinking :deep(.elx-thinking__content pre) {
  max-height: 12rem;
  overflow-y: auto;
  scrollbar-width: thin;
}
.assistant-thinking :deep(.elx-thinking__content pre)::-webkit-scrollbar {
  width: 8px;
}
.assistant-thinking :deep(.elx-thinking__content pre)::-webkit-scrollbar-track {
  background: transparent;
}
.assistant-thinking :deep(.elx-thinking__content pre)::-webkit-scrollbar-thumb {
  border: 2px solid transparent;
  border-radius: var(--ai-r-pill);
  background: color-mix(in srgb, var(--ink) 18%, transparent);
  background-clip: padding-box;
}
</style>
