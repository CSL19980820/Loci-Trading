<script setup lang="ts">
/**
 * 战法监测调参：每段流水线可启停，每档阈值可改。
 *
 * 字段清单由后端 `schema` 描述，这里只负责渲染——后端加了阈值界面自动出现，
 * 不会出现「代码里能调、界面上看不到」。值域同样由后端钳边界。
 */
import { computed, ref, watch } from 'vue'
import { LoaderCircle, TriangleAlert } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { getWatchTuning, resetWatchTuning, saveWatchTuning } from '@/shared/api/quant_ops'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Label } from '@/shared/components/ui/label'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Switch } from '@/shared/components/ui/switch'
import { confirmAction, confirmDangerous } from '@/shared/lib/confirm'
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
    toast.error(toErrorMessage(caught, '读取调参失败'))
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!tuning.value) return
  saving.value = true
  try {
    apply(await saveWatchTuning(props.slug, tuning.value))
    toast.success('调参已保存')
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '保存调参失败'))
  } finally {
    saving.value = false
  }
}

async function reset(): Promise<void> {
  const ok = await confirmDangerous(
    '恢复默认档会丢弃本战法的全部调参，继续？',
    '恢复默认',
    '恢复默认',
  )
  if (!ok) return
  saving.value = true
  try {
    apply(await resetWatchTuning(props.slug))
    toast.success('已恢复默认档')
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '恢复默认失败'))
  } finally {
    saving.value = false
  }
}

async function applyPreset(preset: WatchTuningPreset): Promise<void> {
  const ok = await confirmAction({
    message: `套用「${preset.label}」将覆盖当前全部调参阈值（段开关保留当前值）。\n${preset.summary}\n\n继续？`,
    title: '套用调参预设',
    confirmText: '套用',
    cancelText: '取消',
  })
  if (!ok) return
  saving.value = true
  try {
    apply(await saveWatchTuning(props.slug, { preset: preset.id }))
    toast.success(`已套用「${preset.label}」，可继续手工微调后保存`)
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '套用预设失败'))
  } finally {
    saving.value = false
  }
}

watch(() => props.slug, () => void load(), { immediate: true })

defineExpose({ load })
</script>

<template>
  <div class="relative flex min-w-0 flex-col gap-2">
    <PageBusy :busy="loading" overlay />
    <Alert v-if="disabledStages.length" class="mb-2 shrink-0 text-warn">
      <TriangleAlert />
      <AlertTitle class="line-clamp-none min-w-0">已关闭 {{ disabledStages.map((s) => s.label).join('、') }}，按降级口径运行</AlertTitle>
    </Alert>

    <template v-if="tuning">
      <p v-if="presetOptions.length" class="section dim">调参预设</p>
      <div v-if="presetOptions.length" class="preset-bar mb">
        <Button
          v-for="preset in presetOptions"
          :key="preset.id"
          variant="outline"
          size="sm"
          :disabled="!available || saving"
          @click="applyPreset(preset)"
        >
          {{ preset.label }}
        </Button>
        <span class="dim">一键套用后可继续手工微调</span>
      </div>

      <p class="section dim">流水线开关</p>
      <div class="field-grid">
        <div v-for="stage in stages" :key="stage.key" class="field">
          <Label :for="`tuning-stage-${stage.key}`" class="field__label">{{ stage.label }}</Label>
          <div class="field__control">
            <Switch
              :id="`tuning-stage-${stage.key}`"
              v-model="tuning.stages[stage.key as keyof typeof tuning.stages]"
              :disabled="!available"
            />
            <span class="dim hint">{{ stage.hint }}</span>
          </div>
        </div>
      </div>

      <template v-for="group in sections" :key="group.name">
        <p class="section dim">{{ group.label }}</p>
        <div class="field-grid">
          <div v-for="field in group.fields" :key="field.key" class="field">
            <Label :for="`tuning-${group.name}-${field.key}`" class="field__label">{{ field.label }}</Label>
            <NumberField
              v-model="sectionValues(group.name)[field.key]"
              :step="field.step"
              :min="field.min ?? undefined"
              :max="field.max ?? undefined"
              :disabled="!available"
              class="num"
            >
              <NumberFieldContent>
                <NumberFieldInput :id="`tuning-${group.name}-${field.key}`" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </div>
        </div>
      </template>

      <div class="bar">
        <Button :disabled="!available || saving" @click="save">
          <LoaderCircle v-if="saving" class="size-4 animate-spin" aria-hidden="true" />
          保存调参
        </Button>
        <Button variant="outline" :disabled="!available || saving" @click="reset">
          <LoaderCircle v-if="saving" class="size-4 animate-spin" aria-hidden="true" />
          恢复默认
        </Button>
        <span class="dim">越界值会被后端钳到合法区间</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: var(--gap-2);
}
.section {
  margin: var(--gap-2) 0 var(--gap-1);
}
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}
.hint {
  margin-left: var(--gap-2);
}
.num {
  width: 9rem;
}
.bar {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin-top: var(--gap-2);
  flex-wrap: wrap;
}
.preset-bar {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  flex-wrap: wrap;
}
/* 原 el-form 的 label 右对齐两列栅格：label 6.5em + 控件自适应 */
.field-grid {
  display: grid;
  gap: var(--gap-1);
}
.field {
  display: grid;
  grid-template-columns: 6.5em minmax(0, 1fr);
  align-items: center;
  column-gap: var(--gap-2);
  min-width: 0;
}
.field__label {
  justify-content: flex-end;
  text-align: right;
  color: var(--mist);
  font-size: var(--fs-aux);
  font-weight: 400;
}
.field__control {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--gap-2);
}
</style>
