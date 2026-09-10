<script setup lang="ts">
import { computed } from 'vue'

import { artifactShellTitle, parseSources } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const sources = computed(() => parseSources(props.artifact.data ?? {}))
</script>

<template>
  <section
    class="assistant-source-strip assistant-card assistant-card--tight"
    :aria-label="artifactShellTitle(artifact)"
  >
    <div class="assistant-card__heading">
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
.assistant-source-strip__list { display: flex; flex-wrap: wrap; gap: .35rem; }
.assistant-source-strip__meta {
  margin-left: .25rem; color: var(--mist); font-family: var(--mono); font-size: var(--ai-fs-meta);
}
</style>
