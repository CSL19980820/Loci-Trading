<script setup lang="ts">
import { computed } from 'vue'

import { artifactShellTitle, parseCodePayload } from '../assistantArtifacts'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const payload = computed(() => parseCodePayload(props.artifact.data ?? {}))
</script>

<template>
  <section class="assistant-code-card assistant-card" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-card__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
      <el-tag size="small" type="info">{{ payload.language }}</el-tag>
    </div>
    <pre v-if="payload.text" class="assistant-code-card__pre"><code>{{ payload.text }}</code></pre>
    <EmptyState v-else description="无代码内容" reason="换个问法重问" />
  </section>
</template>

<style scoped>
.assistant-code-card__pre {
  margin: 0; padding: .55rem .65rem; overflow: auto; max-height: 16rem;
  border-radius: var(--ai-r-card); background: color-mix(in oklab, var(--ink) 8%, transparent);
  font-family: var(--mono); font-size: var(--ai-fs-aux); line-height: 1.45; white-space: pre-wrap;
}
</style>
