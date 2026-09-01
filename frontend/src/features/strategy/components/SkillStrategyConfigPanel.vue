<script setup lang="ts">
/**
 * 专属战法 Skill 配置：盘后 AI 选股 Job + 盘中确定性信号监测 Job。
 *
 * 时间全部在这里定（SKILL.md 不写 cron）；只有启用 AI 选股/解读时才要求 LLM。
 */
import { computed, onScopeDispose, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { getProviders } from '@/shared/api/quant'
import { getSkillStrategyConfig, upsertSkillStrategyConfig } from '@/shared/api/quant_ops'
import { toErrorMessage } from '@/shared/lib/errors'
import type { LlmProvider, SkillStrategyConfig } from '@/shared/types/quant'

import SkillScheduleFields from './SkillScheduleFields.vue'
import SkillWatchPreviewPanel from './SkillWatchPreviewPanel.vue'
import SkillWatchTuningPanel from './SkillWatchTuningPanel.vue'
import {
  readFields,
  screenDefaults,
  watchDefaults,
  writeFields,
  type ScheduleFields,
} from './skillSchedule'

const props = defineProps<{ slug: string }>()
const emit = defineEmits<{ saved: [cfg: SkillStrategyConfig] }>()

const loading = ref(false)
const saving = ref(false)
const providers = ref<LlmProvider[]>([])

const provider = ref('')
const thinking = ref('medium')

const screenEnabled = ref(true)
const screenFields = ref<ScheduleFields>(screenDefaults())
const screenNextRuns = ref<string[]>([])
const pushScreen = ref(true)

const watchEnabled = ref(true)
const watchFields = ref<ScheduleFields>(watchDefaults())
const watchNextRuns = ref<string[]>([])
const pushWatch = ref(true)
const watchUseAi = ref(false)
const watchAvailable = ref(false)
const watchUnavailableReason = ref('')
const llmRequired = computed(() => screenEnabled.value || (watchEnabled.value && watchUseAi.value))

let loadToken = 0
/** hydrate 期间不要把服务端预览当成「用户改动」清掉 */
let hydrating = false

onScopeDispose(() => {
  loadToken += 1
})

function hydrate(cfg: SkillStrategyConfig): void {
  hydrating = true
  const flat = cfg as unknown as Record<string, unknown>
  provider.value = String(cfg.provider || provider.value || '')
  thinking.value = String(cfg.thinking || 'medium')

  screenEnabled.value = cfg.screen_schedule_mode !== 'off'
  screenFields.value = readFields(flat, cfg.screen_schedule_mode, screenDefaults(), 'screen_')
  screenNextRuns.value = cfg.screen_next_runs ?? []
  pushScreen.value = cfg.push_wecom !== false

  watchEnabled.value = cfg.watch_schedule_mode !== 'off'
  watchFields.value = readFields(flat, cfg.watch_schedule_mode, watchDefaults(), 'watch_')
  watchNextRuns.value = cfg.watch_next_runs ?? []
  pushWatch.value = cfg.push_watch !== false
  watchUseAi.value = cfg.watch_use_ai === true
  watchAvailable.value = cfg.watch_available === true
  watchUnavailableReason.value = String(cfg.watch_unavailable_reason || '')
  hydrating = false
}

// 用户一改时间，服务端算的 next_runs 就过期了，让组件回落本地估算
watch(screenFields, () => {
  if (!hydrating) screenNextRuns.value = []
})
watch(watchFields, () => {
  if (!hydrating) watchNextRuns.value = []
})

async function load(): Promise<void> {
  const token = ++loadToken
  loading.value = true
  try {
    const [cfg, list] = await Promise.all([getSkillStrategyConfig(props.slug), getProviders()])
    if (token !== loadToken) return
    providers.value = list
    hydrate(cfg)
    if (!provider.value) {
      provider.value = list.find((p) => p.is_default)?.name || list[0]?.name || ''
    }
  } catch (caught: unknown) {
    if (token !== loadToken) return
    ElMessage.error(toErrorMessage(caught, '读取战法配置失败'))
  } finally {
    if (token === loadToken) loading.value = false
  }
}

async function save(): Promise<void> {
  if (llmRequired.value && !provider.value.trim()) {
    ElMessage.warning('启用盘后 AI 选股或盘中 AI 解读时必须选择 LLM 供应商')
    return
  }
  saving.value = true
  try {
    const payload = {
      provider: provider.value.trim(),
      thinking: thinking.value,
      push_wecom: pushScreen.value,
      push_watch: pushWatch.value,
      watch_use_ai: watchUseAi.value,
      ...writeFields(screenFields.value, screenEnabled.value, 'screen_'),
      ...writeFields(watchFields.value, watchEnabled.value, 'watch_'),
    } as unknown as SkillStrategyConfig
    const saved = await upsertSkillStrategyConfig(props.slug, payload)
    hydrate(saved)
    ElMessage.success('战法配置已保存')
    emit('saved', saved)
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '保存失败'))
  } finally {
    saving.value = false
  }
}

watch(
  () => props.slug,
  () => {
    void load()
  },
  { immediate: true },
)

defineExpose({ save, saving, load })
</script>

<template>
  <div v-loading="loading" class="strategy-skill-config">
    <el-tooltip
      placement="bottom-start"
      content="战法本身不带时间；盘中监测走 MCP + 本地量化信号"
    >
      <p class="config-lede mb">盘后走 AI 全量选股，盘中走 MCP 监测；时点在此配</p>
    </el-tooltip>

    <el-form label-position="right" label-width="6.5em" size="small">
      <el-form-item label="LLM" :required="llmRequired">
        <el-select v-model="provider" filterable placeholder="选择供应商" class="full">
          <el-option
            v-for="item in providers"
            :key="item.name"
            :label="item.is_default ? `${item.name}（默认）` : item.name"
            :value="item.name"
          />
        </el-select>
        <span v-if="!llmRequired" class="dim hint">当前仅运行确定性监测，可不配置</span>
      </el-form-item>

      <el-divider content-position="left">盘后选股（AI）</el-divider>
      <el-form-item label="启用">
        <el-switch v-model="screenEnabled" />
      </el-form-item>
      <template v-if="screenEnabled">
        <el-form-item label="推送">
          <el-switch v-model="pushScreen" />
          <span class="dim hint">选股完成后推企微 / Bark</span>
        </el-form-item>
        <SkillScheduleFields
          v-model="screenFields"
          :next-runs="screenNextRuns"
          id-prefix="screen-"
        />
      </template>

      <el-divider content-position="left">盘中监测（信号）</el-divider>
      <el-form-item label="启用">
        <el-switch v-model="watchEnabled" :disabled="!watchAvailable" />
        <span v-if="!watchAvailable" class="dim hint">
          {{ watchUnavailableReason || '悟道 MCP 未装配，监测不可用' }}
        </span>
      </el-form-item>
      <template v-if="watchEnabled">
        <el-form-item label="推送">
          <el-switch v-model="pushWatch" />
          <span class="dim hint">出现闸门或候选变化时推送</span>
        </el-form-item>
        <el-form-item label="AI 解读">
          <el-switch v-model="watchUseAi" />
          <span class="dim hint">仅做证据摘要，不改变确定性信号</span>
        </el-form-item>
        <SkillScheduleFields v-model="watchFields" :next-runs="watchNextRuns" id-prefix="watch-" />
      </template>
    </el-form>

    <el-divider content-position="left">监测调参</el-divider>
    <SkillWatchTuningPanel :slug="props.slug" :available="watchAvailable" />

    <el-divider content-position="left">监测预览</el-divider>
    <SkillWatchPreviewPanel
      :slug="props.slug"
      :available="watchAvailable"
      :unavailable-reason="watchUnavailableReason"
    />
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: var(--gap-2);
}

/* 页头不写介绍段落：这一行是「这页配什么」，长解释挂在外层 el-tooltip 上 */
.config-lede {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--muted);
}
.full {
  width: 100%;
  max-width: 18rem;
}
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}
.hint {
  margin-left: var(--gap-2);
}
</style>
