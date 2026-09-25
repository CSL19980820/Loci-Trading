<script setup lang="ts">
import { ref } from 'vue'
import AssistantPanel from '../../src/features/ai/components/AssistantPanel.vue'
import { TooltipProvider } from '../../src/shared/components/ui/tooltip'
import { Button } from '../../src/shared/components/ui/button'
import type { AiMessage } from '../../src/shared/types/ai_assistant'
const open = ref(false), busy = ref(false)
const bars = Array.from({ length: 42 }, (_, i) => ({ trade_date: new Date(Date.UTC(2026, 7, i + 1)).toISOString().slice(0, 10), open: 18 + i * .07, close: 18.1 + i * .07, high: 18.6 + i * .07, low: 17.6 + i * .07, volume: 9000 + i * 100, amount: 20000000 + i * 10000 }))
const messages = ref<AiMessage[]>([
  { id: 'question', role: 'user', status: 'done', content: '请根据这三只股票的走势，解释观察思路，并给出对应图表。' },
  { id: 'answer', role: 'assistant', status: 'done', thinking: '先核对数据，再整理观察结论。', tool_receipts: [{ call_id: 'quotes', name: '行情数据', status: 'done', elapsed_ms: 960 }], content: '**结论：先核对趋势与成交量，再比较三组数据。**\n\n这是隔离验收的示例内容，不会执行任何交易。正文应当先出现，图表作为补充证据可展开阅读。\n\n**示例甲 [000001](https://example.test/quote)**\n\n- 结构：关注最近区间变化，避免只看单日涨跌。\n- 成交量：比较不同日期的数值。\n- 数据边界：仅使用本页展示的模拟数据。\n\n**示例乙 [000002]([URL] 收 18.24）\n\n历史记录中的网址已脱敏，展示修复不能改动数字。\n\n### 核对步骤\n\n1. 核对数据日期。\n2. 展开图表查看细节。\n3. 返回正文继续阅读。', artifacts: ['示例甲', '示例乙', '示例丙'].map((name, i) => ({ id: `chart-${i}`, kind: 'kline', status: 'ready', data: { name, code: `00000${i + 1}`, bars } })) },
])
Object.assign(window, { __assistantRich: { messages, busy } })
</script>
<template>
  <TooltipProvider><Button access="read" data-testid="open-rich" @click="open = true">打开历史对话</Button>
    <AssistantPanel :open="open" :busy="busy" :sessions="[]" :archived-sessions="[]" rail-tab="active" :messages="messages" :agents="[]" :provider-ready="true" :providers="[{ name:'fixture', models:['deepseek-v4.1-flash'], is_active:true, is_default:true }]" provider="fixture" model="deepseek-v4.1-flash" thinking="medium" @close="open = false" />
  </TooltipProvider>
</template>
