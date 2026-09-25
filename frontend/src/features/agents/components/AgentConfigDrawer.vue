<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { Item } from '@/shared/components/ui/item'
import { computed, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ChevronDown, Cpu, Flag } from '@lucide/vue'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'
import { Switch } from '@/shared/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import PhasePromptEditor from '@/shared/components/PhasePromptEditor.vue'
import { confirmAction } from '@/shared/lib/confirm'
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
/** 供应商一换，旧模型名必然不对，跟着清空（原 el-select 的 @change 行为）。 */
const provider = computed({ get:() => draft.value.provider || undefined, set:(value:string | undefined) => { draft.value.provider = value ?? ''; draft.value.model = '' } })
const model = computed({ get:() => draft.value.model || undefined, set:(value:string | undefined) => { draft.value.model = value ?? '' } })
/** 工作日程的时间档：与旧 `el-time-select` 的 start/step/end 一致，5 分钟一档。 */
function timeSlots(startMinutes:number, endMinutes:number):string[] {
  const slots:string[] = []
  for (let minute = startMinutes; minute <= endMinutes; minute += 5) {
    slots.push(`${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`)
  }
  return slots
}
const REVIEW_TIMES = timeSlots(15 * 60, 23 * 60 + 55)
const PREMARKET_TIMES = timeSlots(6 * 60, 8 * 60 + 55)
const INTRADAY_MINUTES = [5, 10, 15, 30]
/** 多选战法没有对应原语，用带勾选项的下拉承接（原 el-select multiple + collapse-tags）。 */
const pickedStrategies = computed(() => props.options.strategies.filter(method => draft.value.strategies.includes(method.slug)))
const strategiesLabel = computed(() => {
  const picked = pickedStrategies.value
  if (!picked.length) return '不指定时参考全部已启用战法'
  if (picked.length === 1) return picked[0]!.name
  return `已选 ${picked.length} 个战法`
})
function toggleStrategy(slug:string, checked:boolean) {
  const next = new Set(draft.value.strategies)
  if (checked) next.add(slug)
  else next.delete(slug)
  draft.value.strategies = [...next]
}
function applyTemplate(kind: 'leader' | 'custom') {
  if (!props.options?.templates?.[kind]) return
  const tmpl = JSON.parse(JSON.stringify(props.options.templates[kind]))
  draft.value = {
    ...tmpl,
    provider: draft.value.provider || tmpl.provider,
    model: draft.value.model || tmpl.model,
  }
}
watch(open, value => { if (value) { draft.value = JSON.parse(JSON.stringify(props.config)); baseline.value = JSON.stringify(draft.value); invalid.value = ''; section.value = 'identity' } }, { immediate:true })
async function canLeave():Promise<boolean> {
  if (!open.value) return true
  if (props.busy) return false
  if (!dirty.value) return true
  return confirmAction({ message:'未保存的智能体配置将被丢弃。', title:'放弃修改', confirmText:'放弃', cancelText:'继续编辑', danger:true })
}
/** 关掉抽屉的所有路径（X、Esc、遮罩、取消按钮）都先过一遍未保存确认。 */
async function onOpenChange(next:boolean) {
  if (next) { open.value = true; return }
  if (await canLeave()) open.value = false
}
async function close() { if (await canLeave()) open.value = false }
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
  <Sheet :open="open" @update:open="onOpenChange">
    <SheetContent side="right" class="agent-config-sheet w-[min(660px,100vw)] gap-0 p-0 sm:max-w-none" @interact-outside.prevent>
      <SheetHeader class="border-b border-line px-4 py-3 text-left">
        <SheetTitle class="text-title">{{ creating ? '新建股票智能体' : '智能体设置' }}</SheetTitle>
      </SheetHeader>
      <div class="agent-config-body">
        <Alert v-if="error || invalid" variant="destructive" class="drawer-error">
          <AlertTitle class="line-clamp-none">{{ error || invalid }}</AlertTitle>
        </Alert>
        <div v-if="creating" class="template-selector mb-4">
          <Label class="text-xs text-muted-foreground font-medium mb-2 block">选择初始化模板</Label>
          <div class="grid grid-cols-2 gap-2.5">
            <Item as="button"
              type="button"
              class="template-card flex items-start gap-2.5 p-3 rounded-lg border text-left transition-all cursor-pointer"
              :class="draft.kind === 'leader' ? 'border-seal bg-seal-soft/40 shadow-xs' : 'border-rule bg-surface hover:border-rule-strong'"
              @click="applyTemplate('leader')"
            >
              <span class="p-1.5 rounded-md bg-surface text-seal mt-0.5"><Flag class="size-4" /></span>
              <div class="min-w-0">
                <div class="font-semibold text-xs text-ink flex items-center gap-1.5">
                  龙头选手模板
                  <span v-if="draft.kind === 'leader'" class="text-[10px] font-normal px-1 py-0.2 bg-seal text-on-primary rounded">当前</span>
                </div>
                <p class="text-[11px] text-muted-foreground mt-0.5 leading-snug">1进2/接力/龙空龙，预置盘前、竞价与晚间复盘日程</p>
              </div>
            </Item>
            <Item as="button"
              type="button"
              class="template-card flex items-start gap-2.5 p-3 rounded-lg border text-left transition-all cursor-pointer"
              :class="draft.kind !== 'leader' ? 'border-seal bg-seal-soft/40 shadow-xs' : 'border-rule bg-surface hover:border-rule-strong'"
              @click="applyTemplate('custom')"
            >
              <span class="p-1.5 rounded-md bg-surface text-mist mt-0.5"><Cpu class="size-4" /></span>
              <div class="min-w-0">
                <div class="font-semibold text-xs text-ink flex items-center gap-1.5">
                  空白智能体
                  <span v-if="draft.kind !== 'leader'" class="text-[10px] font-normal px-1 py-0.2 bg-seal text-on-primary rounded">当前</span>
                </div>
                <p class="text-[11px] text-muted-foreground mt-0.5 leading-snug">自定义研究方向、仓位与工作日程，自由从零配置</p>
              </div>
            </Item>
          </div>
        </div>
        <Tabs v-model="section">
          <TabsList class="w-full">
            <TabsTrigger value="identity">身份与模型</TabsTrigger>
            <TabsTrigger value="schedule">账户与日程</TabsTrigger>
            <TabsTrigger value="storage">日记与存储</TabsTrigger>
          </TabsList>
        </Tabs>
        <form class="agent-config-form" @submit.prevent="save">
          <section v-show="section === 'identity'">
            <div class="field">
              <div class="field-head">
                <Label for="agent-config-name">智能体名称<span class="field-required" aria-hidden="true">*</span></Label>
                <span class="field-counter">{{ (draft.name || '').length }}/40</span>
              </div>
              <Input id="agent-config-name" v-model="draft.name" maxlength="40" />
            </div>
            <div class="field">
              <div class="field-head">
                <Label for="agent-config-description">工作职责</Label>
                <span class="field-counter">{{ (draft.description || '').length }}/240</span>
              </div>
              <Input id="agent-config-description" v-model="draft.description" maxlength="240" placeholder="用一句话说明这个智能体负责什么" />
            </div>
            <div class="field-pair">
              <div class="field">
                <div class="field-head">
                  <Label for="agent-config-provider">模型供应商<span v-if="draft.enabled" class="field-required" aria-hidden="true">*</span></Label>
                </div>
                <Select v-model="provider">
                  <SelectTrigger id="agent-config-provider" class="w-full" aria-label="模型供应商"><SelectValue placeholder="选择已启用的供应商" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="p in providers" :key="p.id" :value="p.name">{{ p.name }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="field">
                <div class="field-head">
                  <Label for="agent-config-model">模型<span v-if="draft.enabled" class="field-required" aria-hidden="true">*</span></Label>
                </div>
                <Select v-model="model" :disabled="!draft.provider">
                  <SelectTrigger id="agent-config-model" class="w-full" aria-label="模型"><SelectValue placeholder="选择模型" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="modelName in models" :key="modelName" :value="modelName">{{ modelName }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <p v-if="!providers.length" class="help">尚无可用供应商。请先到“设置 → 模型”配置，再启用智能体；当前可保存为暂停状态。</p>
            <div class="field">
              <div class="field-head">
                <Label for="agent-config-strategies">参考工坊战法</Label>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <Button id="agent-config-strategies" variant="outline" class="strategy-trigger" aria-label="参考工坊战法">
                    <span class="strategy-trigger__text">{{ strategiesLabel }}</span>
                    <ChevronDown class="size-4 shrink-0 opacity-50" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" class="strategy-menu">
                  <DropdownMenuCheckboxItem
                    v-for="method in options.strategies"
                    :key="method.slug"
                    :model-value="draft.strategies.includes(method.slug)"
                    @update:model-value="checked => toggleStrategy(method.slug, checked === true)"
                    @select.prevent
                  >{{ method.name }}</DropdownMenuCheckboxItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <PhasePromptEditor v-model:common-prompt="draft.common_prompt" v-model:prompt="draft.prompt" v-model:premarket-prompt="draft.premarket_prompt" v-model:review-prompt="draft.review_prompt" :max-length="100000" />
            <p class="help">提示词只影响这个智能体。账户隔离、资金校验和数量上限由程序执行，不能被提示词覆盖。</p>
          </section>
          <section v-show="section === 'schedule'">
            <h3>独立模拟账户</h3>
            <div class="field">
              <div class="field-head">
                <Label for="agent-config-capital">初始模拟资金（元）</Label>
              </div>
              <NumberField v-model="capital" :min="100" :max="1000000000" :step="10000" :disabled="!creating" :format-options="{ minimumFractionDigits:2, maximumFractionDigits:2, useGrouping:false }">
                <NumberFieldContent>
                  <NumberFieldInput id="agent-config-capital" />
                  <NumberFieldIncrement />
                  <NumberFieldDecrement />
                </NumberFieldContent>
              </NumberField>
            </div>
            <p v-if="!creating" class="help">初始资金创建后固定。追加资金请在账户页操作，系统会单独记入资金流水。</p>
            <div class="field-pair">
              <div class="field">
                <div class="field-head"><Label for="agent-config-daily-selection">每日累计入选上限</Label></div>
                <NumberField v-model="draft.daily_selection_limit" :min="1" :max="leader ? 3 : 20">
                  <NumberFieldContent><NumberFieldInput id="agent-config-daily-selection" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
                </NumberField>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-watch">同时观察上限</Label></div>
                <NumberField v-model="draft.watch_limit" :min="1" :max="leader ? 5 : 20">
                  <NumberFieldContent><NumberFieldInput id="agent-config-watch" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
                </NumberField>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-position">常态持仓上限</Label></div>
                <NumberField v-model="draft.position_limit" :min="1" :max="leader ? 3 : 4">
                  <NumberFieldContent><NumberFieldInput id="agent-config-position" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
                </NumberField>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-temporary">临时持仓上限</Label></div>
                <NumberField v-model="draft.temporary_position_limit" :min="draft.position_limit" :max="leader ? 5 : 8">
                  <NumberFieldContent><NumberFieldInput id="agent-config-temporary" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
                </NumberField>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-max-position">单股最高仓位（%）</Label></div>
                <NumberField v-model="draft.max_position_pct" :min="1" :max="100">
                  <NumberFieldContent><NumberFieldInput id="agent-config-max-position" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
                </NumberField>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-timeout">单轮研究时限（秒）</Label></div>
                <NumberField v-model="draft.timeout_seconds" :min="60" :max="300" :step="30">
                  <NumberFieldContent><NumberFieldInput id="agent-config-timeout" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
                </NumberField>
              </div>
            </div>
            <p class="help">临时上限只用于换股；新买入的T+1锁仓数量仍不能超过常态上限。每日入选名额不会因移出观察而重置。</p>
            <h3>工作日程 <small>北京时间 · 交易所交易日</small></h3>
            <div class="field-pair">
              <div class="field">
                <div class="field-head"><Label for="agent-config-review-time">晚间复盘</Label></div>
                <Select v-model="draft.schedule.review_time">
                  <SelectTrigger id="agent-config-review-time" class="w-full" aria-label="晚间复盘时间"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="slot in REVIEW_TIMES" :key="slot" :value="slot">{{ slot }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-premarket-time">盘前计划</Label></div>
                <Select v-model="draft.schedule.premarket_time">
                  <SelectTrigger id="agent-config-premarket-time" class="w-full" aria-label="盘前计划时间"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="slot in PREMARKET_TIMES" :key="slot" :value="slot">{{ slot }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-auction">竞价研判</Label></div>
                <Input id="agent-config-auction" model-value="09:25" readonly />
              </div>
              <div class="field">
                <div class="field-head"><Label for="agent-config-intraday">盘中研判间隔</Label></div>
                <Select v-model="draft.schedule.intraday_minutes">
                  <SelectTrigger id="agent-config-intraday" class="w-full" aria-label="盘中研判间隔"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="minute in INTRADAY_MINUTES" :key="minute" :value="minute">{{ minute }}分钟</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div class="field">
              <div class="field-head"><Label for="agent-config-intraday-enabled">盘中自主模拟交易</Label></div>
              <div class="switch-row">
                <Switch id="agent-config-intraday-enabled" v-model="draft.schedule.intraday_enabled" />
                <span class="switch-hint">{{ draft.schedule.intraday_enabled ? '启用' : '仅计划与复盘' }}</span>
              </div>
            </div>
            <p class="help">09:25仅判断是否参与及参与条件；连续交易时段重新获取行情后才允许模拟成交。这里不连接实盘账户。</p>
          </section>
          <section v-show="section === 'storage'">
            <h3>日记保留策略</h3><p class="help">满足“超出天数”或“超出条数”之一的旧日记会被分批清理。当天、运行中和最近20次记录始终保留。</p>
            <div class="field">
              <div class="field-head"><Label for="agent-config-retention-days">保留最近多少自然日（0为不按天数清理）</Label></div>
              <NumberField v-model="draft.retention.days" :min="0" :max="3650">
                <NumberFieldContent><NumberFieldInput id="agent-config-retention-days" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
              </NumberField>
            </div>
            <div class="field">
              <div class="field-head"><Label for="agent-config-retention-entries">最多保留多少条（0为不按条数清理）</Label></div>
              <NumberField v-model="draft.retention.max_entries" :min="0" :max="100000" :step="100">
                <NumberFieldContent><NumberFieldInput id="agent-config-retention-entries" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
              </NumberField>
            </div>
            <div class="field">
              <div class="field-head"><Label for="agent-config-retention-hours">清理检查间隔（小时）</Label></div>
              <NumberField v-model="draft.retention.cleanup_hours" :min="1" :max="168">
                <NumberFieldContent><NumberFieldInput id="agent-config-retention-hours" /><NumberFieldIncrement /><NumberFieldDecrement /></NumberFieldContent>
              </NumberField>
            </div>
            <Alert>
              <AlertTitle>清日记，不清财务事实</AlertTitle>
              <AlertDescription>成交记录、资金流水和资金曲线单独保存。累计工作次数不会因日记清理而归零。两个保留条件均为0时关闭自动清理。</AlertDescription>
            </Alert>
          </section>
          <div class="enable-row"><div><strong>启用智能体</strong><p>保存后按工作日程运行，可能产生模型调用费用。</p></div><Switch v-model="draft.enabled" aria-label="启用智能体" /></div>
        </form>
      </div>
      <SheetFooter class="flex-row justify-end gap-2 border-t border-line px-4 py-3">
        <Button access="read" variant="outline" :disabled="busy" @click="close()">取消</Button>
        <Button :disabled="busy" @click="save">
          <Spinner v-if="busy" class="size-4 animate-spin" aria-hidden="true" />
          {{ creating ? '创建智能体' : '保存配置' }}
        </Button>
      </SheetFooter>
    </SheetContent>
  </Sheet>
</template>
<style scoped>
.agent-config-body { flex:1 1 auto; min-height:0; overflow-y:auto; padding:var(--gap-3) var(--gap-4) var(--gap-4); }
.agent-config-form { padding-top:12px; }
.field { margin-bottom:var(--gap-2); }
.field-head { display:flex; align-items:center; justify-content:space-between; gap:var(--gap-2); margin-bottom:var(--gap-1); }
.field-head :deep(label) { color:var(--mist); font-size:var(--fs-aux); font-weight:400; }
.field-required { color:var(--stamp); margin-left:2px; }
.field-counter { color:var(--mist); font-size:var(--fs-kicker); font-variant-numeric:tabular-nums; }
.field-pair { display:grid; grid-template-columns:1fr 1fr; gap:0 20px; }
.strategy-trigger { width:100%; justify-content:space-between; font-weight:400; }
.strategy-trigger__text { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.strategy-menu { width:var(--reka-dropdown-menu-trigger-width); max-height:18rem; }
.switch-row { display:flex; align-items:center; gap:var(--gap-2); min-height:var(--ctl-h); }
.switch-hint { color:var(--muted); font-size:var(--fs-aux); }
h3 { font-size:15px; font-weight:650; margin:18px 0; }small { font-weight:400; color:var(--muted); font-size:12px; margin-left:8px; }.help { color:var(--muted); line-height:1.8; font-size:12px; margin:0 0 20px; }.enable-row { display:flex; justify-content:space-between; align-items:center; gap:20px; border-top:1px solid var(--line); padding-top:20px; margin-top:28px; }.enable-row p { color:var(--muted); font-size:12px; margin:6px 0; }.drawer-error { margin-bottom:16px; }
@media(max-width:480px) { .field-pair { grid-template-columns:1fr; } }
</style>
