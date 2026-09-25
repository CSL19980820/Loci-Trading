<script setup lang="ts">
import { ref } from 'vue'
import UiField from '../../src/shared/components/ui/UiField.vue'
import TextField from '../../src/shared/components/ui/app/TextField.vue'
import DateField from '../../src/shared/components/ui/app/DateField.vue'
import Pager from '../../src/shared/components/ui/app/Pager.vue'
import { EmptyBlock } from '../../src/shared/components/ui/app/presentation'
import { Button } from '../../src/shared/components/ui/button'
import { Progress } from '../../src/shared/components/ui/progress'
import { vBusy } from '../../src/shared/directives/busy'
import ScreenCatalogRail from '../../src/features/strategy/components/ScreenCatalogRail.vue'
import JobsRail from '../../src/features/ops/components/JobsRail.vue'
import type { ScreenCatalogItem } from '../../src/features/strategy/composables/useScreenCatalog'
const password = ref('secret'), description = ref('第一行'), date = ref(['2026-09-22 09:30', '2026-09-23 15:00'])
const changes = ref(0)
const page = ref(1), size = ref(10), busy = ref(true), selected = ref('a'), job = ref<string | null>('a'), kind = ref('all'), status = ref('all')
const rows: ScreenCatalogItem[] = ['a', 'b'].map((id, i) => ({ id, kind: 'engine', slug: id, name: i ? '动量选股' : '趋势选股', description: '', enabled: true, winRate: 60, avgReturn: 2, sample: 120, wins: 72, recentWinRate: 62, decaySignal: null, lastReviewed: '' }))
const jobs = rows.map(row => ({ id: row.id, title: row.name, kindText: '选股', originText: '战法', bound: true, enabled: true, health: 'ok' as const, healthText: '成功', cronText: '工作日 15:05' }))
</script>
<template>
  <main class="audit">
    <h1>共享基础组件交互验收</h1>
    <section class="controls">
      <UiField label="密码" description="可显示、清空并保持焦点"><TextField v-model="password" show-password clearable /></UiField>
      <UiField label="备注" error="模拟必填错误"><TextField v-model="description" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" /></UiField>
      <UiField label="研究时间"><DateField v-model="date" type="datetimerange" value-format="YYYY-MM-DD HH:mm" /></UiField>
      <Pager v-model:current-page="page" v-model:page-size="size" :total="91" @current-change="changes++" />
      <output data-testid="changes">{{ changes }}</output>
      <output data-testid="page">{{ page }} / {{ size }}</output>
      <Progress :model-value="42" aria-label="任务进度" /><Progress :model-value="null" aria-label="正在加载" />
      <div v-busy="busy" class="busy-box">任务等待区域</div><Button access="read" @click="busy = !busy">切换加载</Button>
      <EmptyBlock description="暂无研究结果" />
    </section>
    <section class="rails"><ScreenCatalogRail :rows="rows" :selected-id="selected" kind-filter="all" @select="selected = $event" /><JobsRail :rows="jobs" v-model:selected-id="job" v-model:kind-filter="kind" v-model:status-filter="status" /></section>
    <output data-testid="selection">{{ selected }} / {{ job }}</output>
  </main>
</template>
<style>
html, body, #app { height:auto !important; min-height:100%; overflow:visible !important; }
body { margin:0; }
</style>
<style scoped>
.audit { padding:24px; max-width:960px; margin:auto; color:var(--text-primary); }
h1 { font-size:20px; font-weight:600; margin-bottom:20px; }
.controls { display:grid; grid-template-columns:minmax(0,1fr); gap:16px; }
.rails { display:grid; grid-template-columns:1fr 1fr; gap:24px; height:260px; margin-top:24px; }
.busy-box { height:52px; border:1px solid var(--border-subtle); padding:12px; }
@media(max-width:640px) { .audit { padding:16px; } .rails { grid-template-columns:1fr; height:520px; } }
</style>
