<script setup lang="ts">
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as DateField } from '@/shared/components/ui/app/DateField.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'
import { default as CheckboxField } from '@/shared/components/ui/app/CheckboxField.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, reactive, ref, watch } from 'vue'

import {
  getMcpQuota,
  patchWudaoSettings,
  saveWudaoMcp,
} from '@/shared/api/quant'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import { dialogWidth } from '@/shared/lib/format'
import type { McpQuotaSnapshot, McpServer } from '@/shared/types/quant'

const open = defineModel<boolean>({ required: true })

const props = defineProps<{
  server: McpServer | null
}>()

const emit = defineEmits<{ saved: [] }>()

const busy = ref(false)
const quota = ref<McpQuotaSnapshot | null>(null)

const form = reactive({
  url: '',
  token: '',
  expires_at: '',
  note: '',
  is_active: true,
  verify: true,
  hist_daily_primary: false,
  daily_total: 5000,
  daily_structured: 3000,
  daily_skill: 2000,
  per_minute: 50,
})

/**
 * 今日剩余额度是**读数**，不是异常：原先用 el-alert(info) 常驻在弹窗顶上，
 * 现在改成「调用限额」那一行的行内读数（HeaderStat）。
 */
const quotaRemain = computed(() => {
  if (!quota.value) return ''
  const r = quota.value.remaining
  return `${r.total}（结构化 ${r.structured} · Skill ${r.skill}）`
})

watch(open, (visible) => {
  if (!visible || !props.server) return
  Object.assign(form, {
    url: props.server.url,
    token: '',
    expires_at: props.server.expires_at || '',
    note: props.server.note || '',
    is_active: props.server.is_active,
    verify: true,
    hist_daily_primary: Boolean(props.server.hist_daily_primary),
    daily_total: props.server.quota?.daily_total ?? 5000,
    daily_structured: props.server.quota?.daily_structured ?? 3000,
    daily_skill: props.server.quota?.daily_skill ?? 2000,
    per_minute: props.server.quota?.per_minute ?? 50,
  })
  void getMcpQuota().then((row) => {
    quota.value = row
  })
})

async function submit(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await saveWudaoMcp({
      url: form.url,
      token: form.token || undefined,
      expires_at: form.expires_at || undefined,
      note: form.note,
      is_active: form.is_active,
      verify: form.verify,
    })
    await patchWudaoSettings({
      hist_daily_primary: form.hist_daily_primary,
      quota: {
        daily_total: form.daily_total,
        daily_structured: form.daily_structured,
        daily_skill: form.daily_skill,
        per_minute: form.per_minute,
      },
    })
    emit('saved')
    open.value = false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <DialogPanel
    v-model="open"
    title="悟道 A 股 · 内置 MCP"
    class="ops-dialog"
    :width="dialogWidth()"
    destroy-on-close
  >
    <!--
      开篇那段「与 Cursor / Codex 同一份凭据…」是常驻介绍段，已删：
      它解释的是 API Key，就挂到 API Key 输入框的 tooltip 上。
    -->

    <FormLayout label-position="top">
      <FormField label="MCP 地址">
        <TextField v-model.trim="form.url" />
      </FormField>
      <FormField label="API Key">
        <HintTooltip
          placement="top-start"
          content="与 Cursor / Codex 同一份凭据，只存本机；未配 Key 时自动跳过，不影响其它数据源"
        >
          <TextField
            v-model.trim="form.token"
            type="password"
            show-password
            autocomplete="off"
            placeholder="留空则保留现有 Key"
          />
        </HintTooltip>
      </FormField>
      <FormField label="套餐到期日">
        <DateField
          v-model="form.expires_at"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="过期后自动跳过"
          style="width: 100%"
        />
      </FormField>
      <FormField label="备注">
        <TextField v-model.trim="form.note" />
      </FormField>
      <FormField>
        <ToggleSwitch v-model="form.is_active" active-text="启用" inactive-text="停用" aria-label="启用悟道 MCP" />
      </FormField>
      <FormField>
        <ToggleSwitch
          v-model="form.hist_daily_primary"
          active-text="日 K 同步优先使用悟道（需 Key 有效）"
        />
      </FormField>

      <!-- 标题压成一行：调用限额 + 今日剩余读数 + 第一条控件（日总上限） -->
      <div class="quota-head">
        <h4 class="section">调用限额</h4>
        <HeaderStat v-if="quotaRemain" label="今日剩余" :value="quotaRemain" />
        <FormField label="日总上限" class="quota-head__item">
          <NumberInput v-model="form.daily_total" :min="0" :max="50000" />
        </FormField>
      </div>
      <div class="quota-grid">
        <FormField label="结构化采集">
          <NumberInput v-model="form.daily_structured" :min="0" :max="50000" />
        </FormField>
        <FormField label="Skill / 助手">
          <NumberInput v-model="form.daily_skill" :min="0" :max="50000" />
        </FormField>
        <FormField label="每分钟上限">
          <NumberInput v-model="form.per_minute" :min="0" :max="500" />
        </FormField>
      </div>
      <FormField>
        <CheckboxField v-model="form.verify">保存时握手并刷新工具列表</CheckboxField>
      </FormField>
    </FormLayout>

    <template #footer>
      <ActionButton access="read" @click="open = false">取消</ActionButton>
      <ActionButton tone="primary" :busy="busy" @click="submit">保存</ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
/* 标题 + 读数 + 第一条控件同排；表单项自身的下边距在这一行里清掉 */
.quota-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  margin: var(--gap-3) 0;
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.section {
  margin: 0;
  font-size: var(--fs-body);
}

/* 表单是 label-position="top"，这一项要横过来，才能与标题真的同一行 */
.quota-head__item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 0 auto;
}



/* 三个数字项走全局 .form-grid（auto-fit minmax 自适应列数），不再手写 1fr 1fr */
.quota-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: 0 var(--gap-3);
}
</style>
<style scoped src="./OpsDialogSurface.css"></style>
