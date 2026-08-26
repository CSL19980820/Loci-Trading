<script setup lang="ts">
/** 战法档位的时间输入（定点 / 间隔 + 下次运行预览）。纯受控组件。 */
import { computed } from 'vue'

import {
  HOUR_OPTS,
  INTERVAL_OPTS,
  MINUTE_OPTS,
  pad,
  previewSlots,
  type ScheduleFields,
} from './skillSchedule'

const props = defineProps<{
  modelValue: ScheduleFields
  /** 后端按交易日历算的下次运行；为空时用本地估算兜底 */
  nextRuns?: string[]
  /** 唯一前缀，避免同页两组 el-option 的 key 冲突 */
  idPrefix: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ScheduleFields] }>()

function patch<K extends keyof ScheduleFields>(key: K, value: ScheduleFields[K]): void {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

const slots = computed(() =>
  props.nextRuns?.length ? props.nextRuns : previewSlots(props.modelValue),
)
</script>

<template>
  <el-form-item label="方式">
    <el-radio-group
      :model-value="modelValue.mode"
      @update:model-value="patch('mode', $event as ScheduleFields['mode'])"
    >
      <el-radio-button value="once">定点</el-radio-button>
      <el-radio-button value="interval">间隔</el-radio-button>
    </el-radio-group>
  </el-form-item>

  <el-form-item v-if="modelValue.mode === 'once'" label="交易日">
    <div class="time-row">
      <el-select
        :model-value="modelValue.run_hour"
        class="time-select"
        @update:model-value="patch('run_hour', Number($event))"
      >
        <el-option v-for="h in HOUR_OPTS" :key="`${idPrefix}rh${h}`" :label="pad(h)" :value="h" />
      </el-select>
      <span class="time-sep">:</span>
      <el-select
        :model-value="modelValue.run_minute"
        class="time-select"
        @update:model-value="patch('run_minute', Number($event))"
      >
        <el-option v-for="m in MINUTE_OPTS" :key="`${idPrefix}rm${m}`" :label="pad(m)" :value="m" />
      </el-select>
    </div>
  </el-form-item>

  <template v-else>
    <el-form-item label="时段">
      <div class="time-row">
        <el-select
          :model-value="modelValue.window_start_hour"
          class="time-select"
          @update:model-value="patch('window_start_hour', Number($event))"
        >
          <el-option v-for="h in HOUR_OPTS" :key="`${idPrefix}sh${h}`" :label="pad(h)" :value="h" />
        </el-select>
        <span class="time-sep">:</span>
        <el-select
          :model-value="modelValue.window_start_minute"
          class="time-select"
          @update:model-value="patch('window_start_minute', Number($event))"
        >
          <el-option v-for="m in MINUTE_OPTS" :key="`${idPrefix}sm${m}`" :label="pad(m)" :value="m" />
        </el-select>
        <span class="time-sep">–</span>
        <el-select
          :model-value="modelValue.window_end_hour"
          class="time-select"
          @update:model-value="patch('window_end_hour', Number($event))"
        >
          <el-option v-for="h in HOUR_OPTS" :key="`${idPrefix}eh${h}`" :label="pad(h)" :value="h" />
        </el-select>
        <span class="time-sep">:</span>
        <el-select
          :model-value="modelValue.window_end_minute"
          class="time-select"
          @update:model-value="patch('window_end_minute', Number($event))"
        >
          <el-option v-for="m in MINUTE_OPTS" :key="`${idPrefix}em${m}`" :label="pad(m)" :value="m" />
        </el-select>
      </div>
    </el-form-item>
    <el-form-item label="间隔">
      <el-select
        :model-value="modelValue.interval_minutes"
        class="time-select wide"
        @update:model-value="patch('interval_minutes', Number($event))"
      >
        <el-option
          v-for="m in INTERVAL_OPTS"
          :key="`${idPrefix}iv${m}`"
          :label="`${m} 分钟`"
          :value="m"
        />
      </el-select>
    </el-form-item>
  </template>

  <el-form-item label="预览">
    <div class="preview">
      <span v-for="slot in slots" :key="`${idPrefix}${slot}`" class="mono">{{ slot }}</span>
    </div>
  </el-form-item>
</template>

<style scoped>
.time-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}
.time-select {
  width: 4.5rem;
}
.time-select.wide {
  width: 7rem;
}
.time-sep {
  color: var(--mist);
}
.preview {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
}
.mono {
  font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.8rem;
}
</style>
