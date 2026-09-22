<script setup lang="ts">
import { Check } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { DetailList, DetailItem, Notice } from '@/shared/components/ui/app/presentation'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, ref, watch } from 'vue'



import { publishResearchBacktestRun } from '@/shared/api/quant_research'
import UiField from '@/shared/components/ui/UiField.vue'
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
    toast.success(result.reused ? '相同人工签署已确认' : '人工签署发布已完成')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '人工签署发布失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <DialogPanel
    :model-value="visible"
    title="人工签署发布"
    class="research-modal"
    append-to-body
    width="min(92vw, 640px)"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="close"
  >
    <p class="review-context">签署仅发布研究证据</p>
    <DetailList class="manifest-facts" :column="1" border size="small">
      <DetailItem label="run id"><code>{{ run?.run_id || '未提供' }}</code></DetailItem>
      <DetailItem label="证据摘要"><code>{{ manifestSha256 || '后端未提供' }}</code></DetailItem>
      <DetailItem label="验证状态">{{ run?.validation?.status || '未提供' }}</DetailItem>
    </DetailList>
    <Notice
      v-if="!canPublish"
      tone="error"
      show-icon
      :closable="false"
      title="不满足发布条件：需待签署 + 验证通过 + manifest 摘要"
      class="dialog-alert"
    />
    <Notice v-if="error" tone="error" show-icon :closable="false" :title="error" class="dialog-alert" />
    <div class="mt-2 flex flex-col gap-2">
      <UiField label="审核人" required :error="error && !form.reviewer.trim() ? '请填写审核人' : ''">
        <TextField v-model="form.reviewer" aria-label="审核人" maxlength="128" show-word-limit />
      </UiField>
      <UiField label="审核理由" required :error="error && !form.reason.trim() ? '请填写审核理由' : ''">
        <TextField v-model="form.reason" aria-label="审核理由" type="textarea" :rows="3" maxlength="2000" show-word-limit />
      </UiField>
    </div>
    <template #footer>
      <ActionButton access="read" :disabled="submitting" @click="close">取消</ActionButton>
      <ActionButton tone="primary" :icon="Check" :disabled="!canPublish" :busy="submitting" @click="publish">
        人工签署发布
      </ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.manifest-facts { margin-top: var(--gap-2); }
.manifest-facts code { font: var(--fs-aux) var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.dialog-alert { margin-top: var(--gap-2); }
.publish-form { margin-top: var(--gap-2); }
</style>
<style scoped src="./ResearchSurfaces.css"></style>
