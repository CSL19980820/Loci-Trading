<script setup lang="ts">
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'

/**
 * 价格提醒卡：填代码与价位加一条规则，或试扫一遍看命中几条。
 *
 * 规则与当前战法 slug 无关，所以这张卡自带 useAlertRules，自己拉自己的列表。
 */
import { computed, onMounted } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'

import SettingsPanel from './SettingsPanel.vue'
import { useAlertRules } from '../composables/useAlertRules'

const { alertCode, alertPrice, rules, loadRules, addRule, scanRules } = useAlertRules()

const tableRows = computed(() => rules.value as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 100 },
  { prop: 'name', label: '名称', minWidth: 140 },
  { prop: 'enabled', label: '启用', width: 70, formatter: (row) => (row.enabled ? '是' : '否') },
]

onMounted(() => {
  void loadRules()
})
</script>

<template>
  <SettingsPanel title="价格提醒规则">
    <template #action>
      <ActionButton tone="primary" size="small" @click="addRule">添加</ActionButton>
      <ActionButton size="small" @click="scanRules">试扫</ActionButton>
    </template>
    <FormLayout
      inline
      label-position="left"
      label-width="6.5em"
      size="small"
      class="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1"
      @submit.prevent
    >
      <FormField label="代码">
        <TextField v-model="alertCode" class="w-32" />
      </FormField>
      <FormField label="价≥" class="mb-0">
        <NumberInput v-model="alertPrice" :step="0.01" />
      </FormField>
    </FormLayout>
    <BasicTable
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      row-key="code"
      stripe
      empty-text="还没有规则"
      empty-reason="填好代码与价格后点「添加」"
    />
  </SettingsPanel>
</template>
