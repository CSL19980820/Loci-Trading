<script setup lang="ts">
import { ref } from 'vue'

import { getWecomSettings, saveWecomSettings, testWecomSettings } from '@/shared/api/quant'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { WecomSettings } from '@/shared/types/quant'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const { busy, guard } = useOpsFeedback()

const wecom = ref<WecomSettings>({ configured: false, url_masked: '' })
const wecomUrl = ref('')

async function load(): Promise<void> {
  wecom.value = await getWecomSettings()
}

async function saveWecom(): Promise<void> {
  const saved = await guard(() => saveWecomSettings(wecomUrl.value), '企微 Webhook 已保存')
  if (saved) {
    wecom.value = saved
    wecomUrl.value = ''
  }
}

async function testWecom(): Promise<void> {
  await guard(() => testWecomSettings(), '测试消息已发送')
}

async function clearWecom(): Promise<void> {
  const saved = await guard(() => saveWecomSettings(''), '已清除企微 Webhook')
  if (saved) wecom.value = saved
}

defineExpose({ load })
</script>

<template>
  <Sheet title="企业微信群机器人">
    <el-form label-position="top" @submit.prevent="saveWecom">
      <el-form-item label="Webhook URL">
        <el-input
          v-model.trim="wecomUrl"
          type="password"
          show-password
          placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
        />
      </el-form-item>
      <p v-if="wecom.configured" class="dim mono">已配置：{{ wecom.url_masked }}</p>
      <div class="row-actions">
        <el-button type="primary" :disabled="busy" @click="saveWecom">保存</el-button>
        <el-button :disabled="busy || !wecom.configured" @click="testWecom">测试推送</el-button>
        <el-button text type="danger" :disabled="busy || !wecom.configured" @click="clearWecom">
          清除
        </el-button>
      </div>
    </el-form>
    <p class="form-hint">
      群机器人 → 添加 → 复制 Webhook。可另建「推送」类定时任务（触价/日终简报/选股摘要），
      或在选股/同步任务勾选「完成后推企微」。
    </p>
  </Sheet>
</template>

<style scoped>
.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
</style>
