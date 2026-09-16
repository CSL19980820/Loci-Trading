<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import type { AgentConfig, AgentOptions } from '@/shared/types/stock_agents'
import type { LlmProvider } from '@/shared/types/quant'
const open = defineModel<boolean>({ default:false })
const props = defineProps<{ config:AgentConfig; options:AgentOptions; providers:LlmProvider[]; creating?:boolean; busy?:boolean; error?:string }>()
const emit = defineEmits<{ save:[config:AgentConfig] }>()
const draft = ref<AgentConfig>(JSON.parse(JSON.stringify(props.config)))
const baseline = ref('')
const section = ref('identity')
const invalid = ref('')
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
const leader = computed(() => draft.value.kind === 'leader')
const models = computed(() => props.providers.find(p => p.name === draft.value.provider)?.models ?? [])
const capital = computed({ get:() => draft.value.initial_capital_cents / 100, set:(value:number) => { draft.value.initial_capital_cents = Math.round(value * 100) } })
watch(open, value => { if (value) { draft.value = JSON.parse(JSON.stringify(props.config)); baseline.value = JSON.stringify(draft.value); invalid.value = ''; section.value = 'identity' } }, { immediate:true })
async function canLeave():Promise<boolean> {
  if (!open.value) return true
  if (props.busy) return false
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('未保存的智能体配置将被丢弃。', '放弃修改', { confirmButtonText:'放弃', cancelButtonText:'继续编辑', type:'warning' }); return true }
  catch { return false }
}
async function close(done?:() => void) { if (await canLeave()) { open.value = false; done?.() } }
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate(canLeave)
function save() {
  const value = draft.value
  invalid.value = ''
  if (!value.name.trim()) invalid.value = '请填写智能体名称'
  else if (value.enabled && (!value.provider || !value.model)) invalid.value = '启动前请选择供应商和模型'
  else if (value.temporary_position_limit < value.position_limit) invalid.value = '临时上限不能小于常态持仓上限'
  else if (value.retention.max_entries > 0 && value.retention.max_entries < 20) invalid.value = '至少保留20条日记，或填0关闭条数限制'
  if (!invalid.value) emit('save', JSON.parse(JSON.stringify(value)))
}
defineExpose({ isDirty:() => open.value && dirty.value })
</script>
<template>
  <el-drawer v-model="open" :title="creating ? '新建股票智能体' : '智能体设置'" size="min(660px, 100vw)" :before-close="close" :close-on-click-modal="false" destroy-on-close>
    <el-alert v-if="error || invalid" :title="error || invalid" type="error" :closable="false" show-icon class="drawer-error" />
    <el-tabs v-model="section" stretch><el-tab-pane label="身份与模型" name="identity" /><el-tab-pane label="账户与日程" name="schedule" /><el-tab-pane label="日记与存储" name="storage" /></el-tabs>
    <el-form label-position="top" class="agent-config-form" @submit.prevent="save">
      <section v-show="section === 'identity'">
        <el-form-item label="智能体名称" required><el-input v-model="draft.name" maxlength="40" show-word-limit /></el-form-item>
        <el-form-item label="工作职责"><el-input v-model="draft.description" maxlength="240" placeholder="用一句话说明这个智能体负责什么" /></el-form-item>
        <div class="field-pair"><el-form-item label="模型供应商" :required="draft.enabled"><el-select v-model="draft.provider" placeholder="选择已启用的供应商" filterable @change="draft.model = ''"><el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.name" /></el-select></el-form-item><el-form-item label="模型" :required="draft.enabled"><el-select v-model="draft.model" filterable placeholder="选择模型" :disabled="!draft.provider"><el-option v-for="model in models" :key="model" :label="model" :value="model" /></el-select></el-form-item></div>
        <p v-if="!providers.length" class="help">尚无可用供应商。请先到“设置 → 模型”配置，再启用智能体；当前可保存为暂停状态。</p>
        <el-form-item label="参考工坊战法"><el-select v-model="draft.strategies" multiple filterable clearable collapse-tags placeholder="不指定时参考全部已启用战法"><el-option v-for="method in options.strategies" :key="method.slug" :label="method.name" :value="method.slug" /></el-select></el-form-item>
        <el-form-item label="系统提示词"><el-input v-model="draft.prompt" type="textarea" :rows="13" maxlength="16000" show-word-limit resize="vertical" /></el-form-item>
        <p class="help">提示词只影响这个智能体。账户隔离、资金校验和数量上限由程序执行，不能被提示词覆盖。</p>
      </section>
      <section v-show="section === 'schedule'">
        <h3>独立模拟账户</h3>
        <el-form-item label="初始模拟资金（元）"><el-input-number v-model="capital" :min="100" :max="1000000000" :precision="2" :step="10000" :disabled="!creating" controls-position="right" /></el-form-item>
        <p v-if="!creating" class="help">初始资金创建后固定。追加资金请在账户页操作，系统会单独记入资金流水。</p>
        <div class="field-pair"><el-form-item label="每日累计入选上限"><el-input-number v-model="draft.daily_selection_limit" :min="1" :max="leader ? 3 : 20" /></el-form-item><el-form-item label="同时观察上限"><el-input-number v-model="draft.watch_limit" :min="1" :max="leader ? 3 : 20" /></el-form-item><el-form-item label="常态持仓上限"><el-input-number v-model="draft.position_limit" :min="1" :max="leader ? 3 : 4" /></el-form-item><el-form-item label="临时持仓上限"><el-input-number v-model="draft.temporary_position_limit" :min="draft.position_limit" :max="leader ? 5 : 8" /></el-form-item><el-form-item label="单股最高仓位（%）"><el-input-number v-model="draft.max_position_pct" :min="1" :max="100" /></el-form-item><el-form-item label="单轮研究时限（秒）"><el-input-number v-model="draft.timeout_seconds" :min="60" :max="300" :step="30" /></el-form-item></div>
        <p class="help">临时上限只用于换股；新买入的T+1锁仓数量仍不能超过常态上限。每日入选名额不会因移出观察而重置。</p>
        <h3>工作日程 <small>北京时间 · 交易所交易日</small></h3>
        <div class="field-pair"><el-form-item label="晚间复盘"><el-time-select v-model="draft.schedule.review_time" start="15:00" step="00:05" end="23:55" /></el-form-item><el-form-item label="盘前计划"><el-time-select v-model="draft.schedule.premarket_time" start="06:00" step="00:05" end="08:55" /></el-form-item><el-form-item label="竞价研判"><el-input model-value="09:25" readonly /></el-form-item><el-form-item label="盘中研判间隔"><el-select v-model="draft.schedule.intraday_minutes"><el-option v-for="minute in [5, 10, 15, 30]" :key="minute" :label="`${minute}分钟`" :value="minute" /></el-select></el-form-item></div>
        <el-form-item label="盘中自主模拟交易"><el-switch v-model="draft.schedule.intraday_enabled" active-text="启用" inactive-text="仅计划与复盘" /></el-form-item>
        <p class="help">09:25仅判断是否参与及参与条件；连续交易时段重新获取行情后才允许模拟成交。这里不连接实盘账户。</p>
      </section>
      <section v-show="section === 'storage'">
        <h3>日记保留策略</h3><p class="help">满足“超出天数”或“超出条数”之一的旧日记会被分批清理。当天、运行中和最近20次记录始终保留。</p>
        <el-form-item label="保留最近多少自然日（0为不按天数清理）"><el-input-number v-model="draft.retention.days" :min="0" :max="3650" /></el-form-item>
        <el-form-item label="最多保留多少条（0为不按条数清理）"><el-input-number v-model="draft.retention.max_entries" :min="0" :max="100000" :step="100" /></el-form-item>
        <el-form-item label="清理检查间隔（小时）"><el-input-number v-model="draft.retention.cleanup_hours" :min="1" :max="168" /></el-form-item>
        <el-alert title="清日记，不清财务事实" description="成交记录、资金流水和资金曲线单独保存。累计工作次数不会因日记清理而归零。两个保留条件均为0时关闭自动清理。" type="info" :closable="false" />
      </section>
      <div class="enable-row"><div><strong>启用智能体</strong><p>保存后按工作日程运行，可能产生模型调用费用。</p></div><el-switch v-model="draft.enabled" aria-label="启用智能体" /></div>
    </el-form>
    <template #footer><el-button :disabled="busy" @click="close()">取消</el-button><el-button type="primary" :loading="busy" @click="save">{{ creating ? '创建智能体' : '保存配置' }}</el-button></template>
  </el-drawer>
</template>
<style scoped>
.agent-config-form { padding-top:12px; }.field-pair { display:grid; grid-template-columns:1fr 1fr; gap:0 20px; }.agent-config-form :deep(.el-select),.agent-config-form :deep(.el-input-number) { width:100%; }
h3 { font-size:15px; font-weight:650; margin:18px 0; }small { font-weight:400; color:var(--muted); font-size:12px; margin-left:8px; }.help { color:var(--muted); line-height:1.8; font-size:12px; margin:0 0 20px; }.enable-row { display:flex; justify-content:space-between; align-items:center; gap:20px; border-top:1px solid var(--line); padding-top:20px; margin-top:28px; }.enable-row p { color:var(--muted); font-size:12px; margin:6px 0; }.drawer-error { margin-bottom:16px; }
@media(max-width:480px) { .field-pair { grid-template-columns:1fr; } }
</style>
