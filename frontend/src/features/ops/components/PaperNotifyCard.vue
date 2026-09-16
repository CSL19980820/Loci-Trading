<script setup lang="ts">
/**
 * 通知策略卡：安静时段与 Bark 推送。
 *
 * 自带 useNotifyPolicy，面板不替它转发任何数据。
 */
import { onMounted } from 'vue'

import SettingsPanel from './SettingsPanel.vue'
import { useNotifyPolicy } from '../composables/useNotifyPolicy'

const { quietHours, barkEnabled, barkKey, barkServer, loadNotify, saveNotify, testNotify } =
  useNotifyPolicy()

onMounted(() => {
  void loadNotify()
})
</script>

<template>
  <SettingsPanel title="通知策略">
    <template #action>
      <el-button type="primary" size="small" @click="saveNotify">保存</el-button>
      <el-button size="small" @click="testNotify">测试推送</el-button>
    </template>
    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <el-form-item label="安静时段">
        <el-input v-model="quietHours" placeholder="23:00-07:00，空为关闭" />
      </el-form-item>
      <el-form-item label="Bark" class="mb-0">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <el-switch v-model="barkEnabled" aria-label="启用 Bark 推送" />
          <el-input
            v-model="barkKey"
            class="notify-field"
            aria-label="Bark 设备密钥"
            placeholder="设备密钥"
            :disabled="!barkEnabled"
          />
          <el-input
            v-model="barkServer"
            class="notify-field"
            aria-label="Bark 服务地址"
            placeholder="服务地址，可选"
            :disabled="!barkEnabled"
          />
        </div>
      </el-form-item>
    </el-form>
  </SettingsPanel>
</template>

<style scoped>
.notify-field { flex: 1 1 10rem; min-width: 0; }
</style>
