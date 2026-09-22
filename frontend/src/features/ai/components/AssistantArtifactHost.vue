<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onErrorCaptured, ref, watch } from 'vue'
import { RefreshCw, TriangleAlert } from '@lucide/vue'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/shared/components/ui/accordion'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Spinner } from '@/shared/components/ui/spinner'
import { artifactShellTitle, isKlineKind } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'
import AssistantCodeCard from './AssistantCodeCard.vue'
import AssistantDataTable from './AssistantDataTable.vue'
import AssistantDecisionChart from './AssistantDecisionChart.vue'
import AssistantSourceStrip from './AssistantSourceStrip.vue'

const AssistantEchartsCard = defineAsyncComponent({ loader:() => import('./AssistantEchartsCard.vue'), timeout:15000 })
const AssistantEquityCard = defineAsyncComponent({ loader:() => import('./AssistantEquityCard.vue'), timeout:15000 })
const AssistantKlineCard = defineAsyncComponent({ loader:() => import('./AssistantKlineCard.vue'), timeout:15000 })
const props = defineProps<{ artifact: AiChartArtifact; active?: boolean }>()
const renderError = ref(''), attempt = ref(0), overdue = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
const loading = computed(() => props.artifact.status === 'loading' && props.active && !overdue.value)
const error = computed(() => renderError.value || (props.artifact.status === 'error' ? String(props.artifact.data?.error || '图表数据读取失败') : '')
  || (props.artifact.status === 'loading' && !loading.value ? (overdue.value ? '图表数据尚未返回，请稍后重新提问。' : '本轮未返回完整的图表数据。') : ''))
const kind = computed(() => props.artifact.kind)
watch(() => [props.artifact.id, props.artifact.status], () => {
  clearTimeout(timer); renderError.value = ''; overdue.value = false
  if (props.artifact.status === 'loading') timer = setTimeout(() => { overdue.value = true }, 60000)
}, { immediate:true })
onBeforeUnmount(() => clearTimeout(timer))
onErrorCaptured(() => { renderError.value = '图表组件未能加载或绘制；正文和其他图表不受影响。'; return false })
function retryRender(): void { renderError.value = ''; attempt.value++ }
</script>
<template>
  <div class="assistant-artifact-host" data-testid="assistant-artifact" :aria-busy="loading">
    <Card v-if="loading" class="artifact-loading"><CardContent class="space-y-3 p-4"><div class="flex items-center gap-2 text-sm"><Spinner />正在读取{{ artifactShellTitle(artifact) }}</div><Skeleton class="h-32 w-full" /></CardContent></Card>
    <Alert v-else-if="error" class="artifact-error"><TriangleAlert /><AlertTitle>{{ artifactShellTitle(artifact) }}</AlertTitle><AlertDescription>{{ error }}<Button v-if="renderError" access="read" variant="outline" size="sm" class="mt-3" @click="retryRender"><RefreshCw />重新加载图表</Button></AlertDescription></Alert>
    <template v-else>
      <AssistantKlineCard v-if="isKlineKind(kind)" :key="attempt" :artifact="artifact" />
      <AssistantDataTable v-else-if="kind === 'table'" :artifact="artifact" />
      <AssistantEchartsCard v-else-if="kind === 'echarts' || kind === 'dual_axis'" :key="attempt" :artifact="artifact" />
      <AssistantEquityCard v-else-if="kind === 'equity_curve'" :key="attempt" :artifact="artifact" />
      <AssistantDecisionChart v-else-if="kind === 'candidate_verdict'" :artifact="artifact" />
      <AssistantSourceStrip v-else-if="kind === 'source_strip'" :artifact="artifact" />
      <AssistantCodeCard v-else-if="kind === 'code'" :artifact="artifact" />
      <Accordion v-else type="single" collapsible><AccordionItem value="data"><AccordionTrigger>{{ artifactShellTitle(artifact) }} · 查看数据</AccordionTrigger><AccordionContent><pre class="artifact-raw">{{ JSON.stringify(artifact.data, null, 2) }}</pre></AccordionContent></AccordionItem></Accordion>
    </template>
  </div>
</template>
<style scoped>
.assistant-artifact-host { display:flex; flex-direction:column; width:100%; min-width:0; }
.artifact-loading { box-shadow:none; }.artifact-error { border-color:var(--border-subtle); background:var(--surface-sunken); }
.artifact-raw { max-height:320px; overflow:auto; font:12px/1.7 var(--mono); white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
