<script setup lang="ts">
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'

/**
 * 通知策略卡：安静时段与 Bark 推送。
 *
 * 自带 useNotifyPolicy，面板不替它转发任何数据。
 */
import { onMounted, useId } from 'vue'

import SettingsPanel from './SettingsPanel.vue'
import { useNotifyPolicy } from '../composables/useNotifyPolicy'

const barkFieldsId = useId()
const { quietHours, barkEnabled, barkKey, barkServer, loadNotify, saveNotify, testNotify } =
  useNotifyPolicy()

onMounted(() => {
  void loadNotify()
})
</script>

<template>
  <SettingsPanel title="通知策略">
    <template #action>
      <ActionButton tone="primary" size="small" @click="saveNotify">保存</ActionButton>
      <ActionButton size="small" @click="testNotify">测试推送</ActionButton>
    </template>
    <FormLayout label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <FormField label="安静时段">
        <TextField v-model="quietHours" placeholder="23:00-07:00，空为关闭" />
      </FormField>
      <FormField label="Bark" class="mb-0">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <ToggleSwitch v-model="barkEnabled" aria-label="启用 Bark 推送" />
          <TextField
            v-model="barkKey"
            :id="`${barkFieldsId}-key`"
            class="notify-field"
            aria-label="Bark 设备密钥"
            placeholder="设备密钥"
            :disabled="!barkEnabled"
          />
          <TextField
            v-model="barkServer"
            :id="`${barkFieldsId}-server`"
            class="notify-field"
            aria-label="Bark 服务地址"
            placeholder="服务地址，可选"
            :disabled="!barkEnabled"
          />
        </div>
      </FormField>
    </FormLayout>
  </SettingsPanel>
</template>

<style scoped>
.notify-field { flex: 1 1 10rem; min-width: 0; }
</style>
