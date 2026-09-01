<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download, RefreshRight, Search } from '@element-plus/icons-vue'

import type { ResearchRun } from '@/shared/types/quant'

const props = defineProps<{
  runs: ResearchRun[]
  activeRun: ResearchRun | null
  loading?: boolean
}>()

const emit = defineEmits<{
  load: [runId: string]
  resume: [runId: string]
}>()

const runId = ref('')
const runHref = computed(() => {
  const id = props.activeRun?.id
  return id ? `/api/research/runs/${encodeURIComponent(id)}` : ''
})

function runStatus(value: ResearchRun['status']): string {
  if (value === 'completed') return '已完成'
  if (value === 'running') return '运行中'
  if (value === 'stale') return '已过期'
  return '错误'
}

function runType(value: ResearchRun['status']): 'success' | 'warning' | 'info' | 'danger' {
  if (value === 'completed') return 'success'
  if (value === 'stale') return 'warning'
  if (value === 'error') return 'danger'
  return 'info'
}

function submit(): void {
  emit('load', runId.value)
}
</script>

<template>
  <section class="run-panel" aria-label="研究 run">
    <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
    <!-- 「只列本次会话的 run」这句口径进 tooltip：页面上不留介绍段 -->
    <header class="run-head">
      <el-tooltip placement="bottom-start" content="只列本次会话已创建或读取的 run；持久历史列表要等后端列表接口">
        <h3>研究 run</h3>
      </el-tooltip>
      <form class="run-query" @submit.prevent="submit">
        <el-input
          v-model="runId"
          size="small"
          clearable
          aria-label="研究 run id"
          placeholder="粘贴 run id"
        />
        <el-button size="small" type="primary" :icon="Search" :loading="props.loading" @click="submit">
          读取
        </el-button>
      </form>
    </header>

    <el-table v-if="props.runs.length" :data="props.runs" size="small" row-key="id" highlight-current-row>
      <el-table-column prop="id" label="run id" min-width="190" show-overflow-tooltip />
      <el-table-column label="状态" width="86">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="runType(row.status)">{{ runStatus(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="code" label="标的" width="84" />
      <el-table-column prop="as_of" label="截止日" width="116" />
      <el-table-column label="动作" width="172" fixed="right">
        <template #default="{ row }">
          <el-button text size="small" :loading="props.loading && row.id === props.activeRun?.id" @click="emit('load', row.id)">
            查看
          </el-button>
          <el-button
            v-if="row.status === 'error'"
            text
            size="small"
            :icon="RefreshRight"
            :loading="props.loading && row.id === props.activeRun?.id"
            @click="emit('resume', row.id)"
          >恢复</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="这次会话还没有跑过任务" :image-size="54" />

    <div v-if="props.activeRun" class="run-detail">
      <div class="run-detail-head">
        <span>当前 run <code>{{ props.activeRun.id }}</code></span>
        <el-link v-if="runHref" :href="runHref" target="_blank" rel="noopener noreferrer" :icon="Download">
          查看 run JSON
        </el-link>
      </div>
      <div class="run-facts">
        <span>策略输入 <strong>未在当前研究 run 契约中提供</strong></span>
        <span>行情版本 <code>{{ props.activeRun.market_revision || '—' }}</code></span>
        <span>输入指纹 <code>{{ props.activeRun.input_sha256 || '—' }}</code></span>
      </div>
      <div class="stage-strip" aria-label="研究阶段">
        <el-tag v-for="(stage, name) in props.activeRun.stages" :key="name" size="small" effect="plain" type="success">
          {{ name }} · {{ stage.status }} · {{ stage.output_sha256.slice(0, 12) }}…
        </el-tag>
      </div>
    </div>
  </section>
</template>

<style scoped>
.run-panel { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); overflow: hidden; }
.run-head, .run-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.run-head { padding: 0.82rem 0.9rem; border-bottom: 1px solid var(--rule); }
.run-head h3 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; cursor: help; }
.run-query { display: flex; align-items: center; gap: 0.4rem; min-width: min(100%, 23rem); }
.run-query .el-input { flex: 1 1 auto; }
.run-panel :deep(.el-table) { width: 100%; }
.run-detail { padding: 0.75rem 0.9rem; border-top: 1px solid var(--rule); }
.run-detail-head { align-items: center; color: var(--mist); font-size: 0.78rem; }
.run-detail-head code, .run-facts code { color: var(--ink); font-family: var(--mono); font-size: 0.72rem; overflow-wrap: anywhere; }
.run-facts { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; margin-top: 0.52rem; color: var(--mist); font-size: 0.75rem; }
.run-facts strong { color: var(--seal-ink); font-weight: 600; }
.stage-strip { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.6rem; }
@media (max-width: 700px) { .run-head { flex-direction: column; } .run-query { min-width: 0; width: 100%; } }
</style>
