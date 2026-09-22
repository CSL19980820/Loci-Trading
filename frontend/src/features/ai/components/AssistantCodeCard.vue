<script setup lang="ts">
import { Card } from '@/shared/components/ui/card'
import { Check, Copy } from '@lucide/vue'
import { computed, ref } from 'vue'

import { artifactShellTitle, parseCodePayload } from '../assistantArtifacts'
import { copyTextToClipboard } from '../assistantMessageActions'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Button } from '@/shared/components/ui/button'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

/** 代码卡（ChatGPT code block 一路）：深色头条（语言 + 标题 + 复制）+ 等宽正文，横向可滚。 */
const props = defineProps<{ artifact: AiChartArtifact }>()

const payload = computed(() => parseCodePayload(props.artifact.data ?? Object.create(null)))
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function copy(): Promise<void> {
  if (!payload.value.text) return
  const ok = await copyTextToClipboard(payload.value.text)
  if (!ok) return
  copied.value = true
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copied.value = false
  }, 1600)
}
</script>

<template>
  <Card class="assistant-code-card assistant-card assistant-card--flush" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-code-card__bar">
      <span class="assistant-code-card__lang">{{ payload.language || 'text' }}</span>
      <span class="assistant-code-card__title" :title="artifactShellTitle(artifact)">{{ artifactShellTitle(artifact) }}</span>
      <Button access="read"
        variant="ghost"
        size="xs"
        class="assistant-code-card__copy"
        :disabled="!payload.text"
        :aria-label="copied ? '已复制' : '复制代码'"
        @click="copy"
      >
        <Check v-if="copied" />
        <Copy v-else />
        {{ copied ? '已复制' : '复制' }}
      </Button>
    </div>
    <pre v-if="payload.text" class="assistant-code-card__pre"><code>{{ payload.text }}</code></pre>
    <EmptyState v-else compact description="无代码内容" reason="工具没有返回正文" />
  </Card>
</template>

<style scoped>
.assistant-code-card {
  overflow: hidden;
}

.assistant-code-card__bar {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  min-height: 34px;
  padding: 0 var(--gap-2) 0 var(--gap-3);
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
}

.assistant-code-card__lang {
  flex: 0 0 auto;
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  background: var(--surface-active);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 600;
  text-transform: lowercase;
}

.assistant-code-card__title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.assistant-code-card__copy {
  flex: 0 0 auto;
  color: var(--text-secondary);
}

.assistant-code-card__pre {
  margin: 0;
  max-height: 18rem;
  padding: var(--gap-3);
  overflow: auto;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  line-height: 1.6;
  white-space: pre;
  tab-size: 2;
  scrollbar-width: thin;
}
</style>
