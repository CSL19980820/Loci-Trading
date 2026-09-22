/**
 * 价格提醒规则的读写。
 *
 * 规则是全局的（/api/alert-rules），既不认战法 slug 也不进纸面舱响应；面板上
 * 那张小卡只要「列出 / 添一条 / 试扫」三件事，独立出来后它不必再从面板接数据。
 */
import { ref } from 'vue'
import { toast } from 'vue-sonner'

import { listAlertRules, saveAlertRule, scanAlertRules } from '@/shared/api/quant_ops_paper'

export function useAlertRules() {
  const alertCode = ref('')
  const alertPrice = ref<number | null>(null)
  const rules = ref<Array<Record<string, unknown>>>([])

  async function loadRules(): Promise<void> {
    rules.value = await listAlertRules()
  }

  async function addRule(): Promise<void> {
    if (!alertCode.value.trim() || alertPrice.value == null) {
      toast.warning('请填写代码与价格')
      return
    }
    await saveAlertRule({
      code: alertCode.value.trim(),
      name: `${alertCode.value.trim()} 价格提醒`,
      condition_group: {
        op: 'and',
        conditions: [{ type: 'price', op: '>=', value: alertPrice.value }],
      },
    })
    alertCode.value = ''
    alertPrice.value = null
    await loadRules()
    toast.success('规则已保存')
  }

  async function scanRules(): Promise<void> {
    const result = await scanAlertRules(true)
    toast.info(`试扫命中 ${String(result.triggered ?? 0)} 条`)
  }

  return { alertCode, alertPrice, rules, loadRules, addRule, scanRules }
}
