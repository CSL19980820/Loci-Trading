<script setup lang="ts">
/**
 * 通知策略卡：安静时段与 Bark 推送。
 *
 * 自带 useNotifyPolicy，所以是自洽的一张卡——面板不替它转发任何数据，挂载时
 * 自己问一次设置（原来是面板 onMounted 里三枪并发中的一枪）。
 */
import { onMounted } from 'vue'

import { useNotifyPolicy } from '../composables/useNotifyPolicy'

const { quietHours, barkEnabled, barkKey, barkServer, loadNotify, saveNotify, testNotify } =
  useNotifyPolicy()

onMounted(() => {
  void loadNotify()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>通知策略（安静时段 / Bark）</template>
    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <el-form-item label="安静时段">
        <el-input v-model="quietHours" placeholder="23:00-07:00，空为关闭" />
      </el-form-item>
      <el-form-item label="Bark">
        <el-switch v-model="barkEnabled" />
        <el-input
          v-model="barkKey"
          class="ml"
          placeholder="device_key"
          :disabled="!barkEnabled"
        />
        <el-input
          v-model="barkServer"
          class="ml"
          placeholder="server_url 可选"
          :disabled="!barkEnabled"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="saveNotify">保存</el-button>
        <el-button @click="testNotify">测试推送</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.ml {
  margin-left: var(--gap-2);
}
</style>
