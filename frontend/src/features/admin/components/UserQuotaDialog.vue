<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { setUserQuota } from '@/shared/api/admin'
import type { AdminUserItem, SetQuotaPayload } from '@/shared/types/admin'
import { quotaToUiValue, uiValueToQuota } from '../lib/adminFormat'
import { toErrorMessage } from '@/shared/lib/errors'

const props = defineProps<{
  visible: boolean
  user: AdminUserItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'saved'): void
}>()

const form = reactive({
  llm_tokens_unlimited: false,
  llm_tokens_value: 300000,
  llm_calls_unlimited: false,
  llm_calls_value: 200,
  strategy_unlimited: false,
  strategy_value: 20,
  publish_unlimited: false,
  publish_value: 5,
  jobs_unlimited: false,
  jobs_value: 5,
  storage_unlimited: false,
  storage_value: 2048,
})

/**
 * 六项配额字段表。与 QuotaTab 的批量表同构，但这里每项都提交，
 * 所以不需要「是否调整」开关，只有「不限 / 数值」两态。
 * 长口径进 label 的 tooltip，不再用 `<span class="quota-hint">` 挤 form-item 行高。
 */
const QUOTA_FIELDS: ReadonlyArray<{
  label: string
  hint: string
  unlimited: 'llm_tokens_unlimited' | 'llm_calls_unlimited' | 'strategy_unlimited' | 'publish_unlimited' | 'jobs_unlimited' | 'storage_unlimited'
  value: 'llm_tokens_value' | 'llm_calls_value' | 'strategy_value' | 'publish_value' | 'jobs_value' | 'storage_value'
  step: number
}> = [
  { label: '月 Tokens', hint: '每月 LLM Token 上限', unlimited: 'llm_tokens_unlimited', value: 'llm_tokens_value', step: 50000 },
  { label: '日调用', hint: '每天可向 AI 发起的请求次数', unlimited: 'llm_calls_unlimited', value: 'llm_calls_value', step: 50 },
  { label: '策略槽位', hint: '可创建或保存的私有策略数', unlimited: 'strategy_unlimited', value: 'strategy_value', step: 5 },
  { label: '发布槽位', hint: '可向广场公开发布的策略数', unlimited: 'publish_unlimited', value: 'publish_value', step: 1 },
  { label: '定时任务', hint: '自建定时任务上限；系统托管的选股 / 情报任务不占额度', unlimited: 'jobs_unlimited', value: 'jobs_value', step: 1 },
  { label: '目录 MB', hint: '私有目录软上限；超限只加速清理临时数据，不拒写入', unlimited: 'storage_unlimited', value: 'storage_value', step: 512 },
]

const submitting = ref(false)

watch(
  () => props.user,
  (u) => {
    if (!u) return
    const q = u.quota
    const t = quotaToUiValue(q?.llm_monthly_tokens)
    form.llm_tokens_unlimited = t.unlimited
    form.llm_tokens_value = t.value

    const c = quotaToUiValue(q?.llm_daily_calls)
    form.llm_calls_unlimited = c.unlimited
    form.llm_calls_value = c.value

    const s = quotaToUiValue(q?.strategy_slots)
    form.strategy_unlimited = s.unlimited
    form.strategy_value = s.value

    const p = quotaToUiValue(q?.publish_slots)
    form.publish_unlimited = p.unlimited
    form.publish_value = p.value

    const j = quotaToUiValue(q?.job_slots)
    form.jobs_unlimited = j.unlimited
    form.jobs_value = j.value

    const st = quotaToUiValue(q?.storage_mb)
    form.storage_unlimited = st.unlimited
    form.storage_value = st.value
  },
  { immediate: true },
)

function onClose(): void {
  emit('update:visible', false)
}

async function onSubmit(): Promise<void> {
  if (!props.user || submitting.value) return
  const payload: SetQuotaPayload = {
    llm_monthly_tokens: uiValueToQuota(form.llm_tokens_unlimited, form.llm_tokens_value),
    llm_daily_calls: uiValueToQuota(form.llm_calls_unlimited, form.llm_calls_value),
    strategy_slots: uiValueToQuota(form.strategy_unlimited, form.strategy_value),
    publish_slots: uiValueToQuota(form.publish_unlimited, form.publish_value),
    job_slots: uiValueToQuota(form.jobs_unlimited, form.jobs_value),
    storage_mb: uiValueToQuota(form.storage_unlimited, form.storage_value),
  }

  submitting.value = true
  try {
    await setUserQuota(props.user.id, payload)
    ElMessage.success('配额已更新')
    emit('saved')
    onClose()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '更新配额失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    class="admin-form-dialog dialog-body--scroll"
    :model-value="visible"
    :title="`调整配额 - ${user?.display_name || user?.username}`"
    width="min(92vw, 560px)"
    @close="onClose"
  >
    <el-form
      label-position="top"
      label-width="auto"
      size="small"
      class="quota-form"
      :aria-busy="submitting"
    >
      <el-form-item v-for="field in QUOTA_FIELDS" :key="field.value">
        <template #label>
          <el-tooltip :content="field.hint" placement="top" :show-after="200">
            <span>{{ field.label }}</span>
          </el-tooltip>
        </template>
        <el-input-number
          v-if="!form[field.unlimited]"
          v-model="form[field.value]"
          :min="0"
          :step="field.step"
          controls-position="right"
          class="quota-num"
        />
        <el-checkbox v-model="form[field.unlimited]">不限</el-checkbox>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="onClose">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">保存配额</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.quota-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 13rem), 1fr)); gap: var(--gap-2) var(--gap-3); }
.quota-form :deep(.el-form-item__content) { display: flex; flex-wrap: wrap; gap: var(--gap-2); }
.quota-num { flex: 1 1 8rem; min-width: 0; width: auto; font-family: var(--mono); }
</style>

<style scoped src="./AdminDialog.css" />
