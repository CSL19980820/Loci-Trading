<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioButton } from '@/shared/components/ui/app/RadioButton.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'
import { Button } from '@/shared/components/ui/button'
import { Switch } from '@/shared/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'

import { computed } from 'vue'

import type { WecomSettings } from '@/shared/types/quant'
import type { SyncDraft } from '../composables/useSystemSettings'
import {
  WECOM_PRESET_OPTIONS,
  applyWecomPreset,
  normalizeWecomScreenTemplate,
  previewWecomScreenTemplate,
  type WecomScreenPreset,
  type WecomScreenTemplate,
} from '../composables/wecomScreenTemplate'

/**
 * 推送一节：企微 Webhook → 失败自动推 → 选股样式 → 低吸观察 → （自定义模板）→ 标签与条数 → 预览。
 * 每条是一行设置行；模板 token 按钮与两张预览纸放在整行（stack）里。
 */
const wecomUrl = defineModel<string>('wecomUrl', { required: true })
const screenTemplate = defineModel<WecomScreenTemplate>('screenTemplate', { required: true })

defineProps<{
  sync: SyncDraft
  wecom: WecomSettings
  clearPending: boolean
  /** 真的点不动的情况：正在忙、或压根没有可测的地址 */
  testDisabled: boolean
  /** 有未保存的推送改动：按钮改成「保存并测试」，一次点击把两步做完 */
  testWillSave: boolean
}>()

const emit = defineEmits<{
  clear: []
  test: []
}>()

const isCustom = computed(() => screenTemplate.value.preset === 'custom')
const previewText = computed(() => previewWecomScreenTemplate(screenTemplate.value, 'quant'))
const previewSkills = computed(() => previewWecomScreenTemplate(screenTemplate.value, 'skills'))
const presetHint = computed(
  () => WECOM_PRESET_OPTIONS.find((o) => o.value === screenTemplate.value.preset)?.hint ?? '',
)

type TokenField = 'header' | 'intro' | 'pick' | 'skill_pick'

const CUSTOM_FIELDS: Array<{
  key: keyof WecomScreenTemplate & string
  label: string
  placeholder: string
  tokens?: string[]
  tokenField?: TokenField
  tokenHint?: string
}> = [
  { key: 'header', label: '标题行', placeholder: '【{title}】{kind}', tokens: ['{title}', '{kind}', '{date}'], tokenField: 'header' },
  { key: 'intro', label: '导语', placeholder: '留空则直接展示标的列表', tokens: ['{date}'], tokenField: 'intro' },
  { key: 'pick', label: '每只股票', placeholder: '{name} {code} {pct}', tokens: ['{name}', '{code}', '{pct}'], tokenField: 'pick' },
  { key: 'pick_no_pct', label: '无涨跌幅时', placeholder: '{name} {code}' },
  { key: 'skill_pick', label: '技能 · 每只（含说明）', placeholder: '{name} {code} {pct} + {note}', tokens: ['{note}'], tokenField: 'skill_pick', tokenHint: '{note} 取技能给出的说明，超过 40 字会被截断' },
  { key: 'skill_pick_no_pct', label: '技能 · 无涨跌幅时', placeholder: '{name} {code} + {note}' },
  { key: 'empty', label: '空结果', placeholder: '' },
]

function onPresetChange(value: WecomScreenPreset | string | number | boolean): void {
  const preset = String(value) as WecomScreenPreset
  screenTemplate.value = applyWecomPreset(screenTemplate.value, preset)
}

function markCustom(): void {
  if (screenTemplate.value.preset !== 'custom') {
    screenTemplate.value = { ...screenTemplate.value, preset: 'custom' }
  }
}

function insertToken(field: TokenField, token: string): void {
  markCustom()
  screenTemplate.value = {
    ...screenTemplate.value,
    [field]: `${screenTemplate.value[field] || ''}${token}`,
  }
}

function onCustomFieldEdit(): void {
  markCustom()
  screenTemplate.value = normalizeWecomScreenTemplate(screenTemplate.value)
}

function resetTemplate(): void {
  screenTemplate.value = normalizeWecomScreenTemplate({ preset: 'default' })
}

function fieldValue(key: string): string {
  return String((screenTemplate.value as unknown as Record<string, unknown>)[key] ?? '')
}

function setField(key: string, value: string): void {
  screenTemplate.value = { ...screenTemplate.value, [key]: value }
}
</script>

<template>
  <form class="sys-rows" @submit.prevent>
    <div class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">
          企微机器人
          <UiBadge v-if="wecom.configured && !clearPending" variant="ok" dot>已配置</UiBadge>
          <UiBadge v-else-if="clearPending" variant="warn" dot>待清除</UiBadge>
          <UiBadge v-else variant="secondary" dot>未配置</UiBadge>
        </span>
        
      </div>
      <div class="settings-row__control">
        <TextField
          v-model.trim="wecomUrl"
          type="password"
          show-password
          class="wecom-input"
          aria-label="企微机器人 Webhook"
          :placeholder="
            clearPending
              ? '保存后将清除'
              : wecom.configured
                ? wecom.url_masked || '已配置 · 输入新地址以覆盖'
                : 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…'
          "
        />
      </div>
    </div>

    <div class="settings-row">
      <div class="settings-row__lead">
        <Label class="settings-row__label" for="sys-notify-fail">任务失败自动推送</Label>
        
      </div>
      <div class="settings-row__control">
        <Switch id="sys-notify-fail" v-model="sync.push_wecom_on_fail" aria-label="任务失败自动推送" />
      </div>
    </div>

    <div class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">选股推送样式</span>
        <p class="settings-row__desc">{{ presetHint || '决定一条选股消息长什么样。' }}</p>
      </div>
      <div class="settings-row__control preset-wrap">
        <RadioChoices
          :model-value="screenTemplate.preset"
          aria-label="选股推送样式"
          size="small"
          @change="onPresetChange"
        >
          <RadioButton v-for="opt in WECOM_PRESET_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </RadioButton>
        </RadioChoices>
      </div>
    </div>

    <div class="settings-row">
      <div class="settings-row__lead">
        <Label class="settings-row__label" for="sys-notify-watch">推送低吸观察票</Label>
        <p class="settings-row__desc">关闭后不显示观察票（不计正式胜率的那批）；正式结果为空时直接写「暂无符合条件的标的」。</p>
      </div>
      <div class="settings-row__control">
        <Switch id="sys-notify-watch" v-model="screenTemplate.show_watch_picks" aria-label="推送低吸观察" />
      </div>
    </div>

    <div v-if="isCustom" class="settings-row settings-row--stack">
      <div class="settings-row__lead">
        <span class="settings-row__label">自定义模板</span>
        
      </div>
      <div class="custom-grid">
        <div v-for="f in CUSTOM_FIELDS" :key="f.key" class="custom-field">
          <Label class="custom-field__label" :for="`sys-notify-${f.key}`">{{ f.label }}</Label>
          <TextField
            :id="`sys-notify-${f.key}`"
            :model-value="fieldValue(f.key)"
            :placeholder="f.placeholder"
            size="small"
            @update:model-value="(v: string) => setField(f.key, v)"
            @change="f.tokenField ? onCustomFieldEdit() : undefined"
          />
          <div v-if="f.tokens?.length" class="token-row">
            <template v-for="token in f.tokens" :key="token">
              <Tooltip v-if="f.tokenHint">
                <TooltipTrigger as-child>
                  <Button variant="secondary" size="xs" class="token" @click="insertToken(f.tokenField!, token)">{{ token }}</Button>
                </TooltipTrigger>
                <TooltipContent>{{ f.tokenHint }}</TooltipContent>
              </Tooltip>
              <Button v-else variant="secondary" size="xs" class="token" @click="insertToken(f.tokenField!, token)">{{ token }}</Button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <div class="settings-row">
      <div class="settings-row__lead">
        <span class="settings-row__label">标记与条数</span>
        
      </div>
      <div class="settings-row__control tags-row">
        <Label class="tag-field">
          <span>量化</span>
          <TextField v-model="screenTemplate.quant_tag" maxlength="16" size="small" aria-label="量化标记" />
        </Label>
        <Label class="tag-field">
          <span>技能</span>
          <TextField v-model="screenTemplate.skills_tag" maxlength="16" size="small" aria-label="技能标记" />
        </Label>
        <Label class="tag-field">
          <span>最多</span>
          <NumberInput v-model="screenTemplate.max_picks" :min="1" :max="50" size="small" class="max-picks" aria-label="最多推送条数" />
        </Label>
      </div>
    </div>

    <div class="settings-row settings-row--stack">
      <div class="settings-row__lead settings-row__lead--inline">
        <span class="settings-row__label">预览</span>
        <div class="preview-actions">
          <Button variant="ghost" size="sm" @click="resetTemplate">恢复默认</Button>
          <Button
            variant="ghost"
            size="sm"
            class="text-stamp hover:text-stamp"
            :disabled="!wecom.configured && !clearPending"
            @click="emit('clear')"
          >
            清除地址
          </Button>
          <Button
            size="sm"
            :variant="testWillSave ? 'default' : 'outline'"
            :disabled="testDisabled"
            data-testid="wecom-test"
            @click="emit('test')"
          >
            {{ testWillSave ? '保存并测试' : '发送测试' }}
          </Button>
        </div>
      </div>
      <div class="preview-grid" aria-label="选股推送预览">
        <figure class="preview-tape">
          <figcaption class="preview-label">量化</figcaption>
          <pre class="preview-body">{{ previewText }}</pre>
        </figure>
        <figure class="preview-tape">
          <figcaption class="preview-label">技能</figcaption>
          <pre class="preview-body">{{ previewSkills }}</pre>
        </figure>
      </div>
    </div>
  </form>
</template>

<style scoped>
.sys-rows {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
}

.settings-row__label {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.wecom-input {
  width: 100%;
  min-width: 0;
}

.wecom-input :deep(input) {
  font-family: var(--mono);
  font-size: var(--fs-aux);
}

.preset-wrap :deep(.radio-choices) {
  max-width: 100%;
  overflow-x: auto;
  flex-wrap: nowrap;
  scrollbar-width: none;
}

.custom-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-3) var(--gap-4);
  width: 100%;
}

.custom-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.custom-field__label {
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 500;
}

.token-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-1);
}

.token {
  font-family: var(--mono);
}

.tags-row {
  gap: var(--gap-2) var(--gap-3);
}

.tag-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.tag-field :deep(.text-field) {
  width: 6.5rem;
}

.max-picks {
  width: 6rem;
}

.settings-row__lead--inline {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
}

.preview-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-3);
  width: 100%;
}

.preview-tape {
  margin: 0;
  min-width: 0;
  padding: var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.preview-label {
  margin: 0 0 var(--gap-1);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.preview-body {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 720px) {
  .custom-grid,
  .preview-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
