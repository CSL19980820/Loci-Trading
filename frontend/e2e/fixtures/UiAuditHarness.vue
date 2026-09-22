<script setup lang="ts">
import { ref, provide } from 'vue'
import { VISITOR_MODE } from '../../src/shared/composables/useAccess'
import { TooltipProvider } from '../../src/shared/components/ui/tooltip'
import { SidebarProvider, SidebarTrigger } from '../../src/shared/components/ui/sidebar'
import AppSidebar from '../../src/shared/components/layout/AppSidebar.vue'
import GuardianAccountPanel from '../../src/features/ops/components/GuardianAccountPanel.vue'
import SysAppearanceSection from '../../src/features/ops/components/SysAppearanceSection.vue'
import AssistantPanel from '../../src/features/ai/components/AssistantPanel.vue'
import GuardianMobileHistoryFilter from '../../src/features/ops/components/GuardianMobileHistoryFilter.vue'
import GuardianHoldingCurve from '../../src/features/ops/components/GuardianHoldingCurve.vue'
import ThemeDialog from '../../src/shared/components/dialogs/ThemeDialog.vue'
import TextField from '../../src/shared/components/ui/app/TextField.vue'
import { Button } from '../../src/shared/components/ui/button'
import { useUserStore } from '../../src/shared/stores/user'
import type { AiMessage, AiChartArtifact } from '../../src/shared/types/ai_assistant'

const visitor = ref(false)
provide(VISITOR_MODE, visitor)
const user = useUserStore()
user.user = {id:'ui-test',username:'UI 验收',role:'admin',must_change_password:false} as never
const view = new URLSearchParams(location.search).get('view') || 'assistant'
const panelOpen = ref(true), themeOpen = ref(false)
const password = ref('仅测试内容'), range = ref({start:'2026-09-01',end:'2026-09-21',limit:20,followToday:false})
const selectedCode = ref('')
const account = { equity_cents:10300000,positions:[{code:'000980',name:'模拟标的',quantity:1000,mark_at:'2026-09-21T15:00:00+08:00'}] }
const completeAccount = {
 cash_cents:10000000,equity_cents:10600000,market_value_cents:600000,initial_cash_cents:10000000,
 realized_pnl_cents:0,unrealized_pnl_cents:20000,fees_cents:1000,
 positions:['模拟甲','模拟乙'].map((name,i) => ({name,code:`00098${i}`,quantity:1000,available_quantity:800,
 cost_cents:290000,average_cost:2.9,mark_price_cents:300,market_value_cents:300000,unrealized_pnl_cents:10000,
 mark_at:'2026-09-21T15:00:00+08:00',mark_source:'隔离夹具',holding_plan:i ? '较短的模拟持仓计划。' : '这是用于验证长文本换行和详情滚动的模拟计划。'.repeat(20),
 take_profit_plan:'模拟止盈计划',stop_loss_plan:'模拟止损计划',exit_today_plan:'模拟换仓计划'})),
}
const experience = {version:4,updated_at:'2026-09-21T15:00:00+08:00',items:[1,2,3].map(i => ({
 id:`e${i}`,status:'proposed',hypothesis:i===1 ? '模拟经验。'.repeat(50) : '模拟经验内容',
 validation_plan:'只验证界面，不执行交易。'.repeat(i),evidence_ids:['daily:2026-09-21:3','tool:3'],
})),origins:{e1:{source_report:'daily:2026-09-21:3'}}}
const calls = ref<unknown[]>([])
const bars = Array.from({length:64}, (_,i) => {
 const date = new Date(Date.UTC(2026,6,20+i)).toISOString().slice(0,10)
 const base = 2 + i*.016 + Math.sin(i/5)*.21
 return {trade_date:date,open:+(base+.015).toFixed(2),close:+(base+(i%3===0?-.035:.045)).toFixed(2),high:+(base+.09).toFixed(2),low:+(base-.07).toFixed(2),volume:450000+i*9000,amount:13000000+i*800000}
})
const artifact:AiChartArtifact = {id:'ready-old',kind:'qianlong_kline',title:'000980 日 K',status:'ready',data:{bars}}
const initial:AiMessage[] = [
 {id:'u1',role:'user',content:'查看这只股票的图表。以下为隔离验收的模拟数据，不是真实行情。',status:'done'},
 {id:'a1',role:'assistant',content:'图表和读数如下。价格为测试数据，未调用模型或交易接口。',status:'done',thinking:'检查模拟图表的名称、价格单位与显示状态。',tool_receipts:[{call_id:'t1',name:'market_kline',status:'done',elapsed_ms:960,arguments:{code:'000980'}}],artifacts:[{id:'loading-old',kind:'qianlong_kline',title:'000980 日 K',status:'loading',data:{bars:[]}},artifact]},
]
const messages = ref<AiMessage[]>(initial)
const busy = ref(false)
const providers = [{name:'ui-test',enabled:true,models:['ui-test'],model_catalog:[{id:'ui-test',label:'隔离验收模型',enabled:true,context_window:128000}]}]
const sessions = [{id:'s1',title:'图表与组件验收（模拟数据）',status:'idle',updated_at:'2026-09-21T15:00:00+08:00'},{id:'s2',title:'长标题会话：桌面、移动端与历史图表状态检查',status:'idle',updated_at:'2026-09-20T15:00:00+08:00'}]
function record(event:string,value?:unknown):void { calls.value.push({event,value}) }
Object.assign(window, {__uiAudit:{
 calls, messages,
 setVisitor:(value:boolean) => { visitor.value=value },
 setMessages:(value:AiMessage[]) => {messages.value=value},
 setMode:(mode:string) => {
  busy.value = mode === 'streaming'
  if(mode==='empty') {messages.value=[];return}
  const a={...initial[1]!,status:mode==='streaming'?'streaming':'done',artifacts:mode==='error'?[{...artifact,id:'orphan',status:'loading',title:'未完成图表',data:{bars:[]}}]:initial[1]!.artifacts}
  messages.value=[initial[0]!,a as AiMessage]
 },
 append:(content:string) => {messages.value=[...messages.value,{id:`more-${messages.value.length}`,role:'assistant',status:'done',content}]},
 reset:() => {messages.value=initial;busy.value=false},
}})
</script>
<template>
 <TooltipProvider><SidebarProvider :keyboard-shortcut="false" :persist="false" class="min-h-0">
  <AssistantPanel v-if="view==='assistant'" :open="panelOpen" title="图表与组件验收（模拟数据）" :sessions="sessions as never" :archived-sessions="[]" rail-tab="active" active-id="s1" :messages="messages" :agents="[]" :busy="busy" :provider-ready="true" :providers="providers as never" provider="ui-test" model="ui-test" thinking="medium" @send="record('send',$event)" @cancel="record('cancel');busy=false" @select="record('select',$event)" @create="messages=[]" @close="panelOpen=false" @settings="themeOpen=true" />
  <main v-else-if="view==='curve'" class="audit-curve"><h1>持仓曲线隔离验收 · 模拟数据</h1><GuardianHoldingCurve :account="account as never" v-model:selected-code="selectedCode" /></main>
  <main v-else-if="view==='account'" class="audit-curve"><h1>账户组件隔离验收 · 模拟数据</h1><GuardianAccountPanel :account="completeAccount as never" :experience="experience as never" /></main>
  <template v-else-if="view==='navigation'"><AppSidebar /><main class="audit-navigation"><SidebarTrigger access="read" aria-label="验收侧栏开关" /><h1>导航与表单隔离验收</h1><SysAppearanceSection /></main></template>
  <main v-else class="audit-controls">
   <h1>共享组件隔离验收</h1><p>仅模拟数据，不连接生产写入接口。</p>
   <GuardianMobileHistoryFilter :value="range" @apply="range=$event;record('range',$event)" />
   <TextField v-model="password" show-password clearable aria-label="测试密码" />
   <Button access="read" @click="themeOpen=true">主题与外观</Button>
  </main>
  <ThemeDialog v-model="themeOpen" />
 </SidebarProvider></TooltipProvider>
</template>
<style scoped>.audit-controls { display:flex;flex-direction:column;gap:20px;max-width:600px;width:100%;margin:40px auto;padding:20px; }.audit-curve{display:flex;flex-direction:column;gap:16px;width:100%;height:100dvh;min-height:0;padding:16px}.audit-curve h1{font-size:16px;flex:none}.audit-curve :deep(.holding-curve){flex:1;min-height:0}.audit-navigation{flex:1;min-width:0;padding:20px}</style>
