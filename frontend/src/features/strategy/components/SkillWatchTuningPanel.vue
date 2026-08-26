<script setup lang="ts">
/**
 * 战法监测调参：每段流水线可启停，每档阈值可改。
 *
 * 字段清单由后端 `schema` 描述，这里只负责渲染——后端加了阈值界面自动出现，
 * 不会出现「代码里能调、界面上看不到」。值域同样由后端钳边界。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getWatchTuning, resetWatchTuning, saveWatchTuning } from '@/shared/api/quant_ops'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  WatchTuning,
  WatchTuningPreset,
  WatchTuningResponse,
  WatchTuningSchema,
} from '@/shared/types/quant'

const props = defineProps<{ slug: string; available: boolean }>()

const loading = ref(false)
const saving = ref(false)
const tuning = ref<WatchTuning | null>(null)
const schema = ref<WatchTuningSchema | null>(null)
const presets = ref<WatchTuningPreset[]>([])

const stages = computed(() => schema.value?.stages ?? [])
const sections = computed(() => schema.value?.sections ?? [])
const presetOptions = computed(() => {
  const fromSchema = schema.value?.presets ?? []
  return fromSchema.length ? fromSchema : presets.value
})

const disabledStages = computed(() =>
  stages.value.filter(
    (stage) => tuning.value && tuning.value.stages[stage.key as keyof WatchTuning['stages']] === false,
  ),
)

function apply(response: WatchTuningResponse): void {
  tuning.value = response.tuning
  if (response.schema) schema.value = response.schema
  if (response.presets?.length) presets.value = response.presets
  else if (response.schema?.presets?.length) presets.value = response.schema.presets
}

function sectionValues(name: string): Record<string, number> {
  const current = tuning.value as unknown as Record<string, Record<string, number>> | null
  return current?.[name] ?? {}
}

async function load(): Promise<void> {
  loading.value = true
  try {
    apply(await getWatchTuning(props.slug))
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '读取调参失败'))
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!tuning.value) return
  saving.value = true
  try {
    apply(await saveWatchTuning(props.slug, tuning.value))
    ElMessage.success('调参已保存')
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '保存调参失败'))
  } finally {
    saving.value = false
  }
}

async function reset(): Promise<void> {
  try {
    await ElMessageBox.confirm('恢复默认档会丢弃本战法的全部调参，继续？', '恢复默认', {
      type: 'warning',
    })
  } catch {
    return
  }
  saving.value = true
  try {
    apply(await resetWatchTuning(props.slug))
    ElMessage.success('已恢复默认档')
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '恢复默认失败'))
  } finally {
    saving.value = false
  }
}

async function applyPreset(preset: WatchTuningPreset): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `套用「${preset.label}」将覆盖当前全部调参阈值（段开关保留当前值）。\n${preset.summary}\n\n继续？`,
      '套用调参预设',
      { type: 'warning', confirmButtonText: '套用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    apply(await saveWatchTuning(props.slug, { preset: preset.id }))
    ElMessage.success(`已套用「${preset.label}」，可继续手工微调后保存`)
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '套用预设失败'))
  } finally {
    saving.value = false
  }
}

watch(() => props.slug, () => void load(), { immediate: true })

defineExpose({ load })
</script>

<template>
  <div v-loading="loading" class="watch-tuning">
    <el-alert
      v-if="disabledStages.length"
      type="warning"
      show-icon
      :closable="false"
      class="mb"
      title="以下环节已关闭，本战法监测会按降级口径运行"
      :description="disabledStages.map((s) => s.label).join('、')"
    />

    <template v-if="tuning">
      <p v-if="presetOptions.length" class="section dim">调参预设</p>
      <div v-if="presetOptions.length" class="preset-bar mb">
        <el-button
          v-for="preset in presetOptions"
          :key="preset.id"
          size="small"
          :disabled="!available || saving"
          @click="applyPreset(preset)"
        >
          {{ preset.label }}
        </el-button>
        <span class="dim">一键套用后可继续手工微调</span>
      </div>

      <p class="section dim">流水线开关</p>
      <el-form label-position="left" label-width="7rem" size="small">
        <el-form-item v-for="stage in stages" :key="stage.key" :label="stage.label">
          <el-switch
            v-model="tuning.stages[stage.key as keyof typeof tuning.stages]"
            :disabled="!available"
          />
          <span class="dim hint">{{ stage.hint }}</span>
        </el-form-item>
      </el-form>

      <template v-for="group in sections" :key="group.name">
        <p class="section dim">{{ group.label }}</p>
        <el-form label-position="left" label-width="10rem" size="small">
          <el-form-item v-for="field in group.fields" :key="field.key" :label="field.label">
            <el-input-number
              v-model="sectionValues(group.name)[field.key]"
              :step="field.step"
              :min="field.min ?? undefined"
              :max="field.max ?? undefined"
              :disabled="!available"
              controls-position="right"
              class="num"
            />
          </el-form-item>
        </el-form>
      </template>

      <div class="bar">
        <el-button type="primary" :loading="saving" :disabled="!available" @click="save">
          保存调参
        </el-button>
        <el-button :loading="saving" :disabled="!available" @click="reset">恢复默认</el-button>
        <span class="dim">越界值会被后端钳到合法区间</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.75rem;
}
.section {
  margin: 0.5rem 0 0.35rem;
}
.dim {
  color: var(--mist);
  font-size: 0.76rem;
}
.hint {
  margin-left: 0.5rem;
}
.num {
  width: 9rem;
}
.bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.75rem;
  flex-wrap: wrap;
}
.preset-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
</style>
