<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { saveHithinkMcp } from '@/shared/api/quant'
import type { McpServer } from '@/shared/types/quant'
import { dialogWidth } from '@/shared/lib/format'
import DialogPanel from '@/shared/components/ui/app/DialogPanel.vue'
import FormLayout from '@/shared/components/ui/app/FormLayout.vue'
import FormField from '@/shared/components/ui/app/FormField.vue'
import TextField from '@/shared/components/ui/app/TextField.vue'
import DateField from '@/shared/components/ui/app/DateField.vue'
import ToggleSwitch from '@/shared/components/ui/app/ToggleSwitch.vue'
import CheckboxField from '@/shared/components/ui/app/CheckboxField.vue'
import ActionButton from '@/shared/components/ui/app/ActionButton.vue'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{ server: McpServer | null }>()
const emit = defineEmits<{ saved: [] }>()
const busy = ref(false)
const errorText = ref('')
const form = reactive({ token: '', expires_at: '', note: '', is_active: true, verify: true })

watch(open, (visible) => {
  if (!visible) return
  Object.assign(form, {
    token: '',
    expires_at: props.server?.expires_at || '',
    note: props.server?.note || '',
    is_active: props.server?.is_active ?? true,
    verify: true,
  })
  errorText.value = ''
})

async function submit(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  try {
    await saveHithinkMcp({
      token: form.token || undefined,
      expires_at: form.expires_at,
      note: form.note,
      is_active: form.is_active,
      verify: form.verify,
    })
    form.token = ''
    emit('saved')
    open.value = false
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '保存同花顺配置失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <DialogPanel v-model="open" title="同花顺金融数据 · 内置 MCP" class="ops-dialog" :width="dialogWidth()" destroy-on-close>
    <FormLayout label-position="top">
      <p class="text-sm text-muted-foreground">一份 API Key 供 A 股行情、指数板块、标的检索、基金、期货、期权和行情兜底共用。当前使用官方托管地址。</p>
      <FormField label="API Key">
        <TextField
          v-model.trim="form.token"
          type="password"
          show-password
          autocomplete="off"
          :placeholder="server?.has_token ? '留空则保留现有 Key' : '填写同花顺金融数据 API Key'"
        />
      </FormField>
      <FormField label="到期日">
        <DateField v-model="form.expires_at" type="date" value-format="YYYY-MM-DD" placeholder="可选；过期后自动停用" style="width: 100%" />
      </FormField>
      <FormField label="备注"><TextField v-model.trim="form.note" /></FormField>
      <FormField><ToggleSwitch v-model="form.is_active" active-text="启用" inactive-text="停用" aria-label="启用同花顺金融数据" /></FormField>
      <FormField><CheckboxField v-model="form.verify">保存时握手并发现六个 MCP 服务的工具</CheckboxField></FormField>
      <p v-if="errorText" role="alert" class="text-sm text-destructive">{{ errorText }}</p>
    </FormLayout>
    <template #footer>
      <ActionButton @click="open = false">取消</ActionButton>
      <ActionButton tone="primary" :disabled="busy" @click="submit">保存</ActionButton>
    </template>
  </DialogPanel>
</template>
