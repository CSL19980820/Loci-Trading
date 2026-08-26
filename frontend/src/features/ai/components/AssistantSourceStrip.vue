<script setup lang="ts">
import { computed } from 'vue'

import { artifactShellTitle, parseSources } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

const props = defineProps<{ artifact: AiChartArtifact }>()

const sources = computed(() => parseSources(props.artifact.data ?? {}))
</script>

<template>
  <section class="assistant-source-strip" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-source-strip__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
    </div>
    <div v-if="sources.length" class="assistant-source-strip__list">
      <el-tag
        v-for="(source, index) in sources"
        :key="`${source.label}-${index}`"
        size="small"
        effect="plain"
        class="assistant-source-strip__item"
        :title="[source.detail, source.code, source.date, source.hash].filter(Boolean).join(' · ')"
      >
        {{ source.label }}
        <span v-if="source.code" class="assistant-source-strip__meta">{{ source.code }}</span>
        <span v-if="source.date" class="assistant-source-strip__meta">{{ source.date }}</span>
      </el-tag>
    </div>
    <el-empty v-else :image-size="40" description="无来源条目" />
  </section>
</template>

<style scoped>
.assistant-source-strip {
  margin-top: .15rem; padding: .45rem .55rem; border: 1px solid var(--rule);
  border-radius: var(--radius); background: var(--panel-2); width: 100%; min-width: 0;
}
.assistant-source-strip__heading { margin-bottom: .3rem; }
.assistant-source-strip h3 { margin: 0; font-size: var(--ai-fs-body); }
.assistant-source-strip__list { display: flex; flex-wrap: wrap; gap: .35rem; }
.assistant-source-strip__meta {
  margin-left: .25rem; color: var(--mist); font-family: var(--mono); font-size: var(--ai-fs-meta);
}
</style>
