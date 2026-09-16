<script setup lang="ts">
/*
 * 信号规则维护面板（设置 → 模型与工具 → 信号规则）。
 *
 * 规则口径以前只活在后端代码里：想把「量比 2 倍」改成 1.8，只能去改源码重启。
 * 这里把引擎暴露的规则摆成一行一条：开关 + 口径说明 + 可调参数 + 恢复默认，
 * 改完即时 PUT；失败当场回滚并把后端原话弹出来，绝不留一个「看起来改成功了、
 * 其实库里没变」的界面。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import {
  getSignalRules,
  updateSignalRule,
  type SignalRule,
  type SignalRuleParams,
} from '@/shared/api/signalRules'
import SettingsPanel, { type ReceiptPair } from './SettingsPanel.vue'
import { toParamFields } from '../composables/signalRuleMeta'

const emit = defineEmits<{
  /** 把「N/M 启用」回传给 rail，省得导航上永远挂个「—」 */
  summary: [{ tail: string; state: 'ok' | 'idle' | 'bad' }]
}>()

const rules = ref<SignalRule[]>([])
const loading = ref(false)
const loadError = ref('')
/** 正在 PUT 的规则 id：期间禁掉该行控件，避免连点把两次改动打乱序 */
const savingId = ref('')

const enabledCount = computed(() => rules.value.filter((row) => row.enabled).length)

const receipt = computed((): ReceiptPair[] => [
  { key: '规则', value: `${enabledCount.value}/${rules.value.length} 启用` },
])

function isDefault(rule: SignalRule): boolean {
  const keys = new Set([...Object.keys(rule.params), ...Object.keys(rule.defaults)])
  for (const key of keys) {
    if (rule.params[key] !== rule.defaults[key]) return false
  }
  return true
}

function replaceRule(next: SignalRule): void {
  rules.value = rules.value.map((row) => (row.id === next.id ? next : row))
}

function emitSummary(): void {
  if (!rules.value.length) {
    emit('summary', {
      tail: loadError.value ? '读取失败' : '—',
      state: loadError.value ? 'bad' : 'idle',
    })
    return
  }
  emit('summary', {
    tail: `${enabledCount.value}/${rules.value.length} 启用`,
    state: enabledCount.value > 0 ? 'ok' : 'idle',
  })
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    rules.value = await getSignalRules()
  } catch (caught: unknown) {
    rules.value = []
    loadError.value = toErrorMessage(caught, '读不到信号规则，确认本机服务还在运行')
  } finally {
    loading.value = false
    emitSummary()
  }
}

/**
 * 即时保存。乐观改本地 → PUT → 失败把**改之前那份**整条塞回去。
 *
 * 回滚整条而不是「把这个字段改回去」：后端可能同时夹紧了别的参数，
 * 半条还原会留下一个前后端不一致的行。
 */
async function persist(
  rule: SignalRule,
  next: SignalRule,
  patch: { enabled?: boolean; params?: SignalRuleParams },
): Promise<void> {
  const before = rule
  replaceRule(next)
  savingId.value = rule.id
  try {
    const saved = await updateSignalRule(rule.id, patch)
    // 后端回了最终生效值就以它为准（参数可能被夹紧），没回就保留乐观值
    if (saved) replaceRule(saved)
    emitSummary()
  } catch (caught: unknown) {
    replaceRule(before)
    emitSummary()
    ElMessage.error(`${before.label}保存失败：${toErrorMessage(caught, '后台没有留下原因')}`)
  } finally {
    savingId.value = ''
  }
}

function onToggle(rule: SignalRule, value: boolean): void {
  if (value === rule.enabled) return
  void persist(rule, { ...rule, enabled: value }, { enabled: value })
}

function onParamChange(rule: SignalRule, key: string, value: number | undefined | null): void {
  // el-input-number 清空时给 undefined/null：那不是「改成 0」，是没填完，忽略
  if (value === undefined || value === null || !Number.isFinite(value)) return
  if (rule.params[key] === value) return
  const params = { ...rule.params, [key]: value }
  void persist(rule, { ...rule, params }, { params })
}

function onRestoreDefaults(rule: SignalRule): void {
  if (isDefault(rule)) return
  const params = { ...rule.defaults }
  void persist(rule, { ...rule, params }, { params })
}

/**
 * 口径全文：说明 + 触发口径 + 最少K线，用于 tooltip。
 *
 * 正文里同样三段（分色渲染），这里只是把它们拼成一句给 tooltip。
 * 正文单行截断是 CSS 干的，DOM 里始终是全文，所以两处内容永远一致。
 */
function ruleDigest(rule: SignalRule): string {
  const parts = [rule.description || '后端没有给这条规则写口径说明']
  parts.push(rule.repeatable ? '可重复触发' : '每日只报一次')
  if (rule.minBars) parts.push(`至少 ${rule.minBars} 根K线`)
  return parts.join(' · ')
}

defineExpose({ load })
</script>

<template>
  <SettingsPanel title="信号规则" :receipt="receipt">
    <div v-loading="loading" class="rules-list" :aria-busy="loading">
      <el-alert
        v-if="loadError"
        :title="loadError"
        type="error"
        show-icon
        :closable="false"
      />

      <EmptyState
        v-else-if="!rules.length && !loading"
        description="引擎没有报出规则"
        reason="确认后端信号引擎已启动"
      />

      <div
        v-for="rule in rules"
        :key="rule.id"
        class="rule"
        :class="{ 'rule--off': !rule.enabled }"
      >
        <el-switch
          :model-value="rule.enabled"
          :disabled="savingId === rule.id"
          :aria-label="rule.label"
          @update:model-value="(v: string | number | boolean) => onToggle(rule, Boolean(v))"
        />

        <div class="rule__id">
          <span class="rule__label">{{ rule.label }}</span>
          <span class="rule__code code">{{ rule.id }}</span>
        </div>

        <div class="rule__params">
          <label v-for="field in toParamFields(rule)" :key="field.key" class="rule__param">
            <span class="rule__param-label">{{ field.label }}</span>
            <el-input-number
              :model-value="rule.params[field.key]"
              :aria-label="`${rule.label} · ${field.label}`"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :precision="field.precision"
              :disabled="savingId === rule.id || !rule.enabled"
              :controls="false"
              size="small"
              class="rule__num"
              @change="(v: number | undefined) => onParamChange(rule, field.key, v)"
            />
            <!-- 单位格恒占位（空单位也留）：不留就把同列输入框的右缘挤歪 -->
            <span class="rule__param-unit">{{ field.unit }}</span>
          </label>
          <span v-if="!toParamFields(rule).length" class="rule__noparam">无可调参数</span>
        </div>

        <el-button
          text
          size="small"
          class="rule__reset"
          :disabled="savingId === rule.id || isDefault(rule)"
          @click="onRestoreDefaults(rule)"
        >
          恢复默认
        </el-button>

        <!--
          口径单行截断 + tooltip 全文（ui-spec §8：长解释进 tooltip，正文不留说明段）。
          截断只发生在 CSS 层，DOM 里始终是全文——否则窄屏既看不到全文也搜不到这行字。
        -->
        <el-tooltip :content="ruleDigest(rule)" placement="top" :show-after="240">
          <p class="rule__desc">
            {{ rule.description || '后端没有给这条规则写口径说明' }}
            <span class="rule__meta">· {{ rule.repeatable ? '可重复触发' : '每日只报一次' }}</span>
            <span v-if="rule.minBars" class="rule__meta">· 至少 {{ rule.minBars }} 根K线</span>
          </p>
        </el-tooltip>
      </div>
    </div>
  </SettingsPanel>
</template>

<style scoped>
.rules-list { display: flex; flex-direction: column; gap: var(--gap-2); width: 100%; min-width: 0; max-width: 88rem; }
/* 规则行骨架见下方 .rule：超宽屏封顶 88rem 在模板工具类里，注释留此处备查。 */

.rule {
  /*
   * 两行一条，抄的是本页 `SettingsSection` 的骨架（左槽身份 + 右侧正文）：
   *
   * 第一行只放**控件**（开关 / 身份 / 阈值 / 恢复默认）——它们要在行与行之间成列，
   * 用户是竖着扫阈值的；参数轨吃弹性并右对齐收口，所以 1~3 个参数的行右缘一致。
   * 第二行整宽给口径，于是 45 字的说明不必再省略号（上一版把口径挤在同一行里，
   * 六条全被截断，连「每日只报一次」都看不见）。
   */
  display: grid;
  grid-template-columns:
    auto /* 开关 */
    minmax(9rem, 12rem) /* 名称 + 代码 */
    minmax(0, 1fr) /* 参数轨：吃弹性，内容右对齐 */
    auto; /* 恢复默认 */
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  min-width: 0;
  padding: var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
}

.rule:last-child {
  border-bottom: 1px solid var(--rule);
}

.rule--off .rule__label,
.rule--off .rule__desc {
  color: var(--mist);
}

.rule__id {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--gap-1);
  min-width: 0;
}

.rule__label {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.rule__code {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rule__params {
  /*
   * 逐格成列、靠右收口：1 个参数的行，它的输入框与 3 个参数那行的最后一个
   * 输入框对齐；参数个数不同也不会让右缘参差。
   */
  display: grid;
  grid-auto-flow: column;
  justify-content: end;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.rule__param {
  /* 标签 / 数字 / 单位 三段定轨：同族参数（快线·慢线）在行内与行间都成列 */
  display: grid;
  grid-template-columns: auto 4.5rem 1.5rem;
  align-items: center;
  gap: var(--gap-1);
  font-size: var(--fs-aux);
  color: var(--text-secondary);
}

.rule__param-label {
  white-space: nowrap;
}

.rule__param-unit {
  color: var(--mist);
  white-space: nowrap;
}

.rule__num :deep(input) {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.rule__noparam {
  justify-self: end;
  font-size: var(--fs-aux);
  color: var(--mist);
}

/* 六行各挂一个描边按钮＝六个空控件在抢注意力；无可恢复项时它本就该退到背景里 */
.rule__reset.el-button {
  justify-self: end;
}

.rule__desc {
  /* 第二行：从名称那一栏起整宽铺开，与上一行的身份左缘对齐 */
  grid-column: 2 / -1;
  margin: 0;
  min-width: 0;
  font-size: var(--fs-aux);
  color: var(--text-secondary);
  /* 仍留单行截断：窄屏放不下时省略号 + tooltip，不让某一行撑成三倍高 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rule__meta {
  color: var(--mist);
}

@media (max-width: 900px) {
  .rule {
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: start;
    gap: var(--gap-1) var(--gap-2);
  }

  .rule__params {
    grid-column: 2 / -1;
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-start;
    gap: var(--gap-1) var(--gap-2);
  }

  .rule__desc {
    grid-column: 2 / -1;
    white-space: normal;
  }

  .rule__noparam {
    justify-self: start;
  }
}
</style>
<style scoped>
.rule:focus-within { border-color: var(--seal-border); }
.rule__num { width: 100%; }
.rule--off { background: var(--surface-canvas); }
@media (max-width: 1180px) { .rule { grid-template-columns: auto minmax(0, 1fr) auto; } .rule__params { grid-column: 2 / -1; display: flex; flex-wrap: wrap; justify-content: flex-start; } }
</style>
