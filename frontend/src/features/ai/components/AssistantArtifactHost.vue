<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'

import { artifactShellTitle, isKlineKind } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'
import AssistantCodeCard from './AssistantCodeCard.vue'
import AssistantDataTable from './AssistantDataTable.vue'
import AssistantDecisionChart from './AssistantDecisionChart.vue'
import AssistantSourceStrip from './AssistantSourceStrip.vue'

// 助手宿主常驻 App 根，静态引这三张卡会把 echarts 钉进入口块——而它们只在
// AI 真的返回图表产物时才渲染。异步化后 echarts 独立成块，按需拉取。
const AssistantEchartsCard = defineAsyncComponent(() => import('./AssistantEchartsCard.vue'))
const AssistantEquityCard = defineAsyncComponent(() => import('./AssistantEquityCard.vue'))
const AssistantKlineCard = defineAsyncComponent(() => import('./AssistantKlineCard.vue'))

const props = defineProps<{ artifact: AiChartArtifact }>()

const loading = computed(() => props.artifact.status === 'loading')
const errored = computed(() => props.artifact.status === 'error')
const kind = computed(() => props.artifact.kind)
</script>

<template>
  <div class="assistant-artifact-host" data-testid="assistant-artifact">
    <el-skeleton v-if="loading" animated :rows="4" class="assistant-artifact-host__skeleton">
      <template #template>
        <el-skeleton-item variant="h3" style="width: 40%; margin-bottom: .5rem" />
        <el-skeleton-item variant="rect" style="height: 8rem; width: 100%" />
        <p class="assistant-artifact-host__hint">渲染中…</p>
      </template>
    </el-skeleton>
    <el-alert
      v-else-if="errored"
      type="error"
      :closable="false"
      show-icon
      :title="artifactShellTitle(artifact)"
      description="产物加载失败"
    />
    <AssistantKlineCard v-else-if="isKlineKind(kind)" :artifact="artifact" />
    <AssistantDataTable v-else-if="kind === 'table'" :artifact="artifact" />
    <AssistantEchartsCard v-else-if="kind === 'echarts' || kind === 'dual_axis'" :artifact="artifact" />
    <AssistantEquityCard v-else-if="kind === 'equity_curve'" :artifact="artifact" />
    <AssistantDecisionChart v-else-if="kind === 'candidate_verdict'" :artifact="artifact" />
    <AssistantSourceStrip v-else-if="kind === 'source_strip'" :artifact="artifact" />
    <AssistantCodeCard v-else-if="kind === 'code'" :artifact="artifact" />
    <el-collapse v-else class="assistant-artifact-host__unknown">
      <el-collapse-item :title="`未知产物 · ${kind}`" name="json">
        <pre>{{ JSON.stringify(artifact.data, null, 2) }}</pre>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.assistant-artifact-host { width: 100%; min-width: 0; }
.assistant-artifact-host__skeleton {
  padding: .55rem; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--panel-2);
}
.assistant-artifact-host__hint { margin: .4rem 0 0; color: var(--mist); font-size: var(--ai-fs-aux); }
.assistant-artifact-host__unknown { margin-top: .15rem; }
.assistant-artifact-host__unknown pre {
  margin: 0; max-height: 12rem; overflow: auto; font-family: var(--mono); font-size: var(--ai-fs-meta);
  white-space: pre-wrap;
}
</style>
