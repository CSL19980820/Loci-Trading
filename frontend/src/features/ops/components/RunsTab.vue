<script setup lang="ts">
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { firstLine, formatLlmMeta, statusLabel } from '../composables/opsLabels'
import { useJobRunsQuery } from '../composables/useJobRunsQuery'

const emit = defineEmits<{
  'go-jobs': []
}>()

const { runs, refetch } = useJobRunsQuery(() => ({ limit: 20 }))

async function load(): Promise<void> {
  await refetch()
}

defineExpose({ load })
</script>

<template>
  <Sheet title="执行历史">
    <div v-if="runs.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>时间</th>
            <th>任务</th>
            <th>触发</th>
            <th class="r">耗时</th>
            <th>LLM</th>
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td class="mono dim">{{ run.started_at }}</td>
            <td>{{ run.job_name }}</td>
            <td class="dim">{{ run.trigger }}</td>
            <td class="r mono">{{ run.duration_ms }} ms</td>
            <td class="mono dim">{{ formatLlmMeta(run) }}</td>
            <td :class="run.status === 'failed' ? 'tone-down' : ''">
              {{ statusLabel(run.status) }}
              <span v-if="run.error_text" class="dim">{{ firstLine(run.error_text) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      description="还没有执行记录"
      reason="还没有手动或定时执行过任务"
      eta="在「定时任务」点执行后出现"
    >
      <el-button type="primary" @click="emit('go-jobs')">去定时任务</el-button>
    </EmptyState>
  </Sheet>
</template>
