<script setup lang="ts">
import { X as CloseBold } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { DetailList, DetailItem, Notice } from '@/shared/components/ui/app/presentation'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, ref, watch } from 'vue'



import { rejectResearchBacktestRun } from '@/shared/api/quant_research'
import UiField from '@/shared/components/ui/UiField.vue'
import type {
  ResearchBacktestRejectionResult,
  ResearchBacktestRun,
} from '@/shared/types/quant-research'

const props = defineProps<{
  visible: boolean
  run: ResearchBacktestRun | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  rejected: [result: ResearchBacktestRejectionResult]
}>()

const submitting = ref(false)
const error = ref('')
const form = ref({ reviewer: '', reason: '' })

const manifestSha256 = computed(() => props.run?.artifact_manifest_sha256 || '')
const canReject = computed(() => (
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

async function reject(): Promise<void> {
  const run = props.run
  if (!run || !canReject.value) {
    error.value = '当前 run 未满足人工否决条件，请刷新后核对状态和验证结果'
    return
  }
  if (!form.value.reviewer.trim() || !form.value.reason.trim()) {
    error.value = '请填写否决人和否决理由'
    return
  }

  submitting.value = true
  error.value = ''
  try {
    const result = await rejectResearchBacktestRun(run.run_id, {
      // 否决同样只绑定服务端给出的 manifest，浏览器绝不重新计算摘要。
      manifest_sha256: manifestSha256.value,
      reviewer: form.value.reviewer.trim(),
      reason: form.value.reason.trim(),
    })
    emit('rejected', result)
    emit('update:visible', false)
    toast.success(result.reused ? '相同人工否决已确认' : '人工否决已记录')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '人工否决失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <DialogPanel
    :model-value="visible"
    title="人工否决"
    class="research-modal"
    append-to-body
    width="min(92vw, 640px)"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="close"
  >
    <p class="review-context">否决将保留审核回执</p>
    <DetailList class="manifest-facts" :column="1" border size="small">
      <DetailItem label="run id"><code>{{ run?.run_id || '未提供' }}</code></DetailItem>
      <DetailItem label="证据摘要"><code>{{ manifestSha256 || '后端未提供' }}</code></DetailItem>
      <DetailItem label="验证状态">{{ run?.validation?.status || '未提供' }}</DetailItem>
    </DetailList>
    <Notice
      v-if="!canReject"
      tone="error"
      show-icon
      :closable="false"
      title="不满足否决条件：需待签署 + 验证通过 + manifest 摘要"
      class="dialog-alert"
    />
    <Notice v-if="error" tone="error" show-icon :closable="false" :title="error" class="dialog-alert" />
    <div class="mt-2 flex flex-col gap-2">
      <UiField label="否决人" required :error="error && !form.reviewer.trim() ? '请填写否决人' : ''">
        <TextField v-model="form.reviewer" aria-label="否决人" maxlength="128" show-word-limit />
      </UiField>
      <UiField label="否决理由" required :error="error && !form.reason.trim() ? '请填写否决理由' : ''">
        <TextField v-model="form.reason" aria-label="否决理由" type="textarea" :rows="3" maxlength="2000" show-word-limit />
      </UiField>
    </div>
    <template #footer>
      <ActionButton access="read" :disabled="submitting" @click="close">取消</ActionButton>
      <ActionButton tone="danger" :icon="CloseBold" :disabled="!canReject" :busy="submitting" @click="reject">
        记录人工否决
      </ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.manifest-facts { margin-top: var(--gap-2); }
.manifest-facts code { font: var(--fs-aux) var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.dialog-alert { margin-top: var(--gap-2); }
.rejection-form { margin-top: var(--gap-2); }
</style>
<style scoped src="./ResearchSurfaces.css"></style>
