<script setup lang="ts">
import { computed } from 'vue'

import { artifactShellTitle, parseCodePayload } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

const props = defineProps<{ artifact: AiChartArtifact }>()

const payload = computed(() => parseCodePayload(props.artifact.data ?? {}))
</script>

<template>
  <section class="assistant-code-card" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-code-card__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
      <el-tag size="small" type="info">{{ payload.language }}</el-tag>
    </div>
    <pre v-if="payload.text" class="assistant-code-card__pre"><code>{{ payload.text }}</code></pre>
    <el-empty v-else :image-size="40" description="无代码内容" />
  </section>
</template>

<style scoped>
.assistant-code-card {
  margin-top: .15rem; padding: .55rem; border: 1px solid var(--rule);
  border-radius: var(--radius); background: var(--panel-2); width: 100%; min-width: 0;
}
.assistant-code-card__heading {
  display: flex; align-items: center; justify-content: space-between; gap: .4rem; margin-bottom: .35rem;
}
.assistant-code-card h3 { margin: 0; font-size: var(--ai-fs-body); }
.assistant-code-card__pre {
  margin: 0; padding: .55rem .65rem; overflow: auto; max-height: 16rem;
  border-radius: var(--ai-r-card); background: color-mix(in srgb, var(--ink) 8%, transparent);
  font-family: var(--mono); font-size: var(--ai-fs-aux); line-height: 1.45; white-space: pre-wrap;
}
</style>
