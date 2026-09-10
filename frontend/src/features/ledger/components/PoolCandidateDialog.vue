<script setup lang="ts">
/**
 * 候选详情弹窗：一条候选的九项事实 + evidence 原文 + 三个动作。
 *
 * 与列表页只共享「当前选中的那条候选」。战法 / 池 / 来源三处文案由页面解析完再传
 * 进来（JobDetailPane 同一套写法）：弹窗自己不认 slug、不碰战法目录，也就不必知道
 * 筛选与分页那一套。删除与看档案都往外抛——批次会话与列表刷新归页面管。
 */
import { computed } from 'vue'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { decisionLabel, timingLabel } from '@/shared/lib/format'
import type { OpenBatchInput } from '@/shared/stores/batchBrowse'
import type { Candidate } from '@/shared/types/palace'

const props = defineProps<{
  candidate: Candidate | null
  /** 战法中文名（页面查目录解析好） */
  strategyText: string
  /** 池号：战法中文名 · 候选日 */
  poolText: string
  /** 写入来源中文名 */
  sourceText: string
  batch: Omit<OpenBatchInput, 'focusCode'> | null
}>()

const emit = defineEmits<{ delete: [row: Candidate]; archive: [] }>()

const open = defineModel<boolean>({ required: true })

const title = computed(() =>
  props.candidate ? `${props.candidate.name} · ${props.candidate.date}` : '候选详情',
)

const evidenceText = computed(() => {
  const ev = props.candidate?.evidence
  if (!ev || !Object.keys(ev).length) return ''
  return JSON.stringify(ev, null, 2)
})
</script>

<template>
  <el-dialog v-model="open" :title="title" width="52rem" destroy-on-close>
    <template v-if="candidate">
      <el-descriptions
        class="pool-detail-desc"
        :column="2"
        border
        size="small"
        label-width="var(--form-label-w)"
      >
        <el-descriptions-item label="日期">{{ candidate.date }}</el-descriptions-item>
        <el-descriptions-item label="标的">
          <StockLink
            :code="candidate.code"
            :name="candidate.name"
            :date="candidate.date"
            :batch="batch"
          />
        </el-descriptions-item>
        <el-descriptions-item label="战法">{{ strategyText }}</el-descriptions-item>
        <el-descriptions-item label="裁决">{{ decisionLabel(candidate.decision) }}</el-descriptions-item>
        <el-descriptions-item label="时点">{{ timingLabel(candidate.timing) }}</el-descriptions-item>
        <el-descriptions-item label="评分">{{ candidate.score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="池">{{ poolText }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ sourceText }}</el-descriptions-item>
        <el-descriptions-item label="理由" :span="2">{{ candidate.reason }}</el-descriptions-item>
      </el-descriptions>
      <pre v-if="evidenceText" class="evidence">{{ evidenceText }}</pre>
    </template>
    <template #footer>
      <el-button @click="open = false">关闭</el-button>
      <el-button v-if="candidate" type="danger" plain @click="emit('delete', candidate)">删除</el-button>
      <el-button v-if="candidate" type="primary" @click="emit('archive')">看档案</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.evidence {
  margin: var(--gap-2) 0 0;
  padding: var(--gap-2);
  border-radius: var(--radius);
  background: var(--sheet-alt);
  font: var(--fs-aux) / 1.45 var(--mono);
  overflow: auto;
  max-height: 16rem;
  white-space: pre-wrap;
  word-break: break-word;
}
.pool-detail-desc :deep(.el-descriptions__label) {
  width: var(--form-label-w);
  min-width: var(--form-label-w);
  max-width: var(--form-label-w);
  white-space: nowrap;
  vertical-align: top;
}
.pool-detail-desc :deep(.el-descriptions__content) {
  min-width: 0;
  word-break: break-word;
}
</style>
