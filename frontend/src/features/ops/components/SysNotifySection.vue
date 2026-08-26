<script setup lang="ts">
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

const wecomUrl = defineModel<string>('wecomUrl', { required: true })
const screenTemplate = defineModel<WecomScreenTemplate>('screenTemplate', { required: true })

defineProps<{
  sync: SyncDraft
  wecom: WecomSettings
  clearPending: boolean
  testDisabled: boolean
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

function onPresetChange(value: WecomScreenPreset | string | number | boolean): void {
  const preset = String(value) as WecomScreenPreset
  screenTemplate.value = applyWecomPreset(screenTemplate.value, preset)
}

function markCustom(): void {
  if (screenTemplate.value.preset !== 'custom') {
    screenTemplate.value = { ...screenTemplate.value, preset: 'custom' }
  }
}

function insertToken(
  field: 'header' | 'intro' | 'pick' | 'skill_pick',
  token: string,
): void {
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
</script>

<template>
  <el-form class="sys-form" label-position="left" label-width="5.5rem" @submit.prevent>
    <el-form-item label="企微机器人">
      <div class="wecom-row">
        <el-input
          v-model.trim="wecomUrl"
          type="password"
          show-password
          class="wecom-input"
          :placeholder="
            clearPending
              ? '保存后将清除'
              : wecom.configured
                ? wecom.url_masked || '已配置 · 输入新地址以覆盖'
                : 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…'
          "
        />
        <el-tag v-if="wecom.configured && !clearPending" size="small" type="success" effect="plain">
          已配
        </el-tag>
        <el-tag v-else-if="clearPending" size="small" type="warning" effect="plain">待清除</el-tag>
        <el-tag v-else size="small" type="info" effect="plain">未配</el-tag>
        <span class="fail-label">失败自动推</span>
        <el-switch v-model="sync.push_wecom_on_fail" />
      </div>
    </el-form-item>

    <el-form-item label="选股样式">
      <div class="preset-wrap">
        <el-radio-group
          :model-value="screenTemplate.preset"
          size="small"
          @change="onPresetChange"
        >
          <el-radio-button
            v-for="opt in WECOM_PRESET_OPTIONS"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </el-radio-button>
        </el-radio-group>
        <span class="hint">{{ presetHint }}</span>
      </div>
    </el-form-item>

    <template v-if="isCustom">
      <el-row :gutter="12">
        <el-col :xs="24" :md="12">
          <el-form-item label="标题行">
            <el-input
              v-model="screenTemplate.header"
              placeholder="【{title}】{kind}"
              @change="onCustomFieldEdit"
            />
            <div class="token-row">
              <el-button size="small" @click="insertToken('header', '{title}')">{title}</el-button>
              <el-button size="small" @click="insertToken('header', '{kind}')">{kind}</el-button>
              <el-button size="small" @click="insertToken('header', '{date}')">{date}</el-button>
            </div>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item label="导语">
            <el-input
              v-model="screenTemplate.intro"
              placeholder="留空则直接展示标的列表"
              @change="onCustomFieldEdit"
            />
            <div class="token-row">
              <el-button size="small" @click="insertToken('intro', '{date}')">{date}</el-button>
            </div>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item label="每只股票">
            <el-input
              v-model="screenTemplate.pick"
              placeholder="{name} {code} {pct}"
              @change="onCustomFieldEdit"
            />
            <div class="token-row">
              <el-button size="small" @click="insertToken('pick', '{name}')">{name}</el-button>
              <el-button size="small" @click="insertToken('pick', '{code}')">{code}</el-button>
              <el-button size="small" @click="insertToken('pick', '{pct}')">{pct}</el-button>
            </div>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <el-form-item label="无涨跌幅">
            <el-input v-model="screenTemplate.pick_no_pct" placeholder="{name} {code}" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item label="技能·每只（含说明）">
            <el-input
              v-model="screenTemplate.skill_pick"
              placeholder="{name} {code} {pct} + {note}"
              @change="onCustomFieldEdit"
            />
            <div class="token-row">
              <el-button size="small" @click="insertToken('skill_pick', '{note}')">{note}</el-button>
              <span class="hint">说明 ≤40 字</span>
            </div>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <el-form-item label="技能·无涨跌幅">
            <el-input
              v-model="screenTemplate.skill_pick_no_pct"
              placeholder="{name} {code} + {note}"
            />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <el-form-item label="空结果">
            <el-input v-model="screenTemplate.empty" />
          </el-form-item>
        </el-col>
      </el-row>
    </template>

    <el-row :gutter="12">
      <el-col :xs="12" :sm="8" :md="5">
        <el-form-item label="量化标记">
          <el-input v-model="screenTemplate.quant_tag" maxlength="16" />
        </el-form-item>
      </el-col>
      <el-col :xs="12" :sm="8" :md="5">
        <el-form-item label="skills">
          <el-input v-model="screenTemplate.skills_tag" maxlength="16" />
        </el-form-item>
      </el-col>
      <el-col :xs="24" :sm="16" :md="14">
        <el-form-item label="最多推送">
          <div class="inline-actions">
            <el-input-number v-model="screenTemplate.max_picks" :min="1" :max="50" />
            <el-button link @click="resetTemplate">恢复默认</el-button>
            <el-button
              link
              type="danger"
              :disabled="!wecom.configured && !clearPending"
              @click="emit('clear')"
            >
              清除
            </el-button>
            <el-button size="small" :disabled="testDisabled" @click="emit('test')">测试</el-button>
          </div>
        </el-form-item>
      </el-col>
    </el-row>

    <el-form-item label="预览">
      <div class="preview-grid" aria-label="选股推送预览">
        <figure class="preview-tape">
          <figcaption class="preview-label">量化</figcaption>
          <pre class="preview-body">{{ previewText }}</pre>
        </figure>
        <figure class="preview-tape">
          <figcaption class="preview-label">skills</figcaption>
          <pre class="preview-body">{{ previewSkills }}</pre>
        </figure>
      </div>
    </el-form-item>
  </el-form>
</template>

<style scoped>
.wecom-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.55rem;
  width: 100%;
}

.wecom-input {
  flex: 1 1 14rem;
  min-width: 0;
}

.fail-label {
  margin-left: 0.15rem;
  font-size: 0.82rem;
  color: var(--mist);
  white-space: nowrap;
}

.preset-wrap {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.7rem;
}

.hint {
  color: var(--mist);
  font-size: 0.76rem;
  line-height: 1.35;
}

.token-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.3rem;
}

.inline-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem 0.4rem;
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.85rem;
  width: 100%;
}

.preview-tape {
  margin: 0;
  padding: 0.35rem 0 0.15rem 0.65rem;
  border-left: 2px solid color-mix(in srgb, var(--seal, var(--ink)) 35%, var(--rule));
  min-width: 0;
}

.preview-label {
  margin: 0 0 0.25rem;
  font-family: var(--mono);
  font-size: 0.66rem;
  letter-spacing: 0.06em;
  color: var(--mist);
  text-transform: uppercase;
}

.preview-body {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--mono);
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--ink);
}

.sys-form :deep(.el-form-item) {
  margin-bottom: 0.45rem;
}

@media (max-width: 720px) {
  .preview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
