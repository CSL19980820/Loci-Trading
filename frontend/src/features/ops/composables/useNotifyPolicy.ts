/**
 * 通知策略（安静时段 / Bark）的读写。
 *
 * 从纸面量化面板里拆出来的理由很直白：它走 /api/settings/notify，与纸面舱没有
 * 一个共享字段，当初只因为「同一屏能一起改」才挤进同一个 script setup。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  getNotifySettings,
  saveNotifySettings,
  testNotifySettings,
  type NotifySettings,
} from '@/shared/api/quant_ops'

export function useNotifyPolicy() {
  const quietHours = ref('')
  const barkEnabled = ref(false)
  const barkKey = ref('')
  const barkServer = ref('')

  async function loadNotify(): Promise<void> {
    const n: NotifySettings = await getNotifySettings()
    quietHours.value = n.quiet_hours || ''
    barkEnabled.value = Boolean(n.bark?.enabled)
    barkKey.value = n.bark?.device_key || ''
    barkServer.value = n.bark?.server_url || ''
  }

  async function saveNotify(): Promise<void> {
    await saveNotifySettings({
      quiet_hours: quietHours.value,
      bark: {
        enabled: barkEnabled.value,
        device_key: barkKey.value,
        server_url: barkServer.value,
      },
    })
    ElMessage.success('通知策略已保存')
    await loadNotify()
  }

  async function testNotify(): Promise<void> {
    await testNotifySettings()
    ElMessage.success('测试推送已发送')
  }

  return { quietHours, barkEnabled, barkKey, barkServer, loadNotify, saveNotify, testNotify }
}
