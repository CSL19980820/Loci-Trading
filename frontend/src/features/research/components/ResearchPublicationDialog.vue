<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { publishResearchBacktestRun } from '@/shared/api/quant_research'
import type {
  ResearchBacktestPublicationResult,
  ResearchBacktestRun,
} from '@/shared/types/quant-research'

const props = defineProps<{
  visible: boolean
  run: ResearchBacktestRun | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  published: [result: ResearchBacktestPublicationResult]
}>()

const submitting = ref(false)
const error = ref('')
const form = ref({ reviewer: '', reason: '' })

const manifestSha256 = computed(() => props.run?.artifact_manifest_sha256 || '')
const canPublish = computed(() => (
  props.run?.status === 'awaiting_human_review'
  && props.run.validation?.status === 'passed'
  && Boolean(manifestSha256.value)
))

watch(() => props.visible, (visible) => {
  if (!visible) return
  error.value = ''
  form.value = { reviewer: '', reason: '' }
})

function close(): void {
  if (!submitting.value) emit('update:visible', false)
}

async function publish(): Promise<void> {
  const run = props.run
  if (!run || !canPublish.value) {
    error.value = '当前 run 未满足人工签署发布条件，请刷新后核对状态和验证结果'
    return
  }
  if (!form.value.reviewer.trim() || !form.value.reason.trim()) {
    error.value = '请填写审核人和审核理由'
    return
  }

  submitting.value = true
  error.value = ''
  try {
    const result = await publishResearchBacktestRun(run.run_id, {
      // 只回传后端随 run card 返回的摘要，页面绝不自行计算或替换 hash。
      manifest_sha256: manifestSha256.value,
      reviewer: form.value.reviewer.trim(),
      reason: form.value.reason.trim(),
    })
    emit('published', result)
    emit('update:visible', false)
    ElMessage.success(result.reused ? '相同人工签署已确认' : '人工签署发布已完成')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '人工签署发布失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="人工签署发布"
    width="min(92vw, 640px)"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="close"
  >
    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="签署只发布研究证据，不改生产参数"
    />
    <el-descriptions class="manifest-facts" :column="1" border size="small">
      <el-descriptions-item label="run id"><code>{{ run?.run_id || '未提供' }}</code></el-descriptions-item>
      <el-descriptions-item label="artifact manifest SHA-256"><code>{{ manifestSha256 || '后端未提供' }}</code></el-descriptions-item>
      <el-descriptions-item label="验证状态">{{ run?.validation?.status || '未提供' }}</el-descriptions-item>
    </el-descriptions>
    <el-alert
      v-if="!canPublish"
      type="error"
      show-icon
      :closable="false"
      title="不满足发布条件：需待签署 + 验证通过 + manifest 摘要"
      class="dialog-alert"
    />
    <el-alert v-if="error" type="error" show-icon :closable="false" :title="error" class="dialog-alert" />
    <el-form class="publish-form" label-position="right" label-width="6.5em" size="small" @submit.prevent="publish">
      <el-form-item label="审核人" required>
        <el-input v-model="form.reviewer" maxlength="128" show-word-limit />
      </el-form-item>
      <el-form-item label="审核理由" required>
        <el-input v-model="form.reason" type="textarea" :rows="3" maxlength="2000" show-word-limit />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="submitting" @click="close">取消</el-button>
      <el-button type="primary" :icon="Check" :disabled="!canPublish" :loading="submitting" @click="publish">
        人工签署发布
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.manifest-facts { margin-top: var(--gap-2); }
.manifest-facts code { font: var(--fs-aux) var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.dialog-alert { margin-top: var(--gap-2); }
.publish-form { margin-top: var(--gap-2); }
</style>
