<script setup lang="ts">
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioChoice } from '@/shared/components/ui/app/RadioChoice.vue'
import { default as DateField } from '@/shared/components/ui/app/DateField.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, reactive, watch } from 'vue'

import type { UniversePreset } from '@/shared/types/quant'

const visible = defineModel<boolean>({ default: false })

const props = defineProps<{
  formulaName: string
  presets: UniversePreset[]
  defaultPresetId?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  confirm: [payload: {
    mode: 'single' | 'range'
    tradeDate: string
    start: string
    end: string
    presetId: string
  }]
}>()

const form = reactive({
  mode: 'single' as 'single' | 'range',
  tradeDate: '',
  start: '',
  end: '',
  presetId: '',
})

watch(
  () => [visible.value, props.defaultPresetId] as const,
  ([open]) => {
    if (!open) return
    if (!form.presetId) form.presetId = props.defaultPresetId || props.presets[0]?.id || ''
  },
)

const canConfirm = computed(() => {
  if (form.mode === 'single') return Boolean(form.tradeDate)
  return Boolean(form.start && form.end && form.start <= form.end)
})

const dateRange = computed<[string, string] | null>({
  get: (): [string, string] | null => form.start && form.end ? [form.start, form.end] : null,
  set: (value) => { form.start = value?.[0] ?? ''; form.end = value?.[1] ?? '' },
})

function submit(): void {
  if (!canConfirm.value) return
  emit('confirm', {
    mode: form.mode,
    tradeDate: form.tradeDate,
    start: form.start,
    end: form.end,
    presetId: form.presetId,
  })
}
</script>

<template>
  <DialogPanel
    v-model="visible"
    title="选股范围"
    width="min(32rem, 94vw)"
    append-to-body
    :close-on-click-modal="!busy"
  >
    <p class="select-dialog__hint">
      公式：{{ formulaName || '未命名公式' }} · 试跑已通过
    </p>
    <FormLayout label-position="right" label-width="6.5em" size="small" @submit.prevent="submit">
      <FormField label="选股日">
        <RadioChoices v-model="form.mode">
          <RadioChoice value="single">单日</RadioChoice>
          <RadioChoice value="range">区间</RadioChoice>
        </RadioChoices>
      </FormField>
      <FormField v-if="form.mode === 'single'" label="日期">
        <DateField
          v-model="form.tradeDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择交易日"
          style="width: 100%"
        />
      </FormField>
      <FormField v-else label="区间">
        <DateField
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          aria-label="选股区间"
          style="width: 100%"
        />
      </FormField>
      <FormField label="股票池">
        <ChoiceField v-model="form.presetId" clearable placeholder="使用草稿默认池" style="width: 100%">
          <ChoiceOption
            v-for="item in presets"
            :key="item.id"
            :label="item.label"
            :value="item.id"
          />
        </ChoiceField>
      </FormField>
    </FormLayout>
    <template #footer>
      <ActionButton access="read" :disabled="busy" @click="visible = false">取消</ActionButton>
      <ActionButton tone="primary" :busy="busy" :disabled="!canConfirm" @click="submit">
        开始选股
      </ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.select-dialog__hint {
  margin: 0 0 0.85rem;
  color: var(--muted);
  font-size: 0.84rem;
}

.select-dialog__note {
  margin: 0 0 0 5rem;
  color: var(--mist);
  font-size: var(--fs-aux);
}

.select-dialog__sep {
  display: inline-block;
  width: 8%;
  text-align: center;
  color: var(--mist);
}
</style>
