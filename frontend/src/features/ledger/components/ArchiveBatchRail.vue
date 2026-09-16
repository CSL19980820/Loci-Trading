<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, ArrowRight, Back, List } from '@element-plus/icons-vue'

import { parseBatchSource } from '@/shared/lib/batchBrowse'

const props = defineProps<{
  positionLabel: string
  source: string
  canPrev: boolean
  canNext: boolean
  dockOpen: boolean
}>()

const emit = defineEmits<{
  prev: []
  next: []
  'return-batch': []
  'toggle-dock': []
}>()

const parsed = computed(() => parseBatchSource(props.source))
const dockLabel = computed(() => (props.dockOpen ? '收起本批' : '本批'))
</script>

<template>
  <div class="batch-rail ml-auto inline-flex min-w-0 shrink-0 flex-wrap items-center gap-x-2 gap-y-1" aria-label="同批切票">
    <el-button size="small" class="batch-rail__back" :icon="Back" @click="emit('return-batch')">
      返回本批
    </el-button>
    <div class="batch-rail__stepper" role="group" :aria-label="`同批 ${positionLabel}`">
      <el-button
        size="small"
        circle
        :icon="ArrowLeft"
        :disabled="!canPrev"
        aria-label="上一只"
        aria-keyshortcuts="ArrowLeft"
        @click="emit('prev')"
      />
      <span class="batch-rail__pos mono">{{ positionLabel }}</span>
      <el-button
        size="small"
        circle
        :icon="ArrowRight"
        :disabled="!canNext"
        aria-label="下一只"
        aria-keyshortcuts="ArrowRight"
        @click="emit('next')"
      />
    </div>
    <el-button size="small" plain :icon="List" :aria-expanded="dockOpen" @click="emit('toggle-dock')">
      {{ dockLabel }}
    </el-button>
    <!-- 侧栏已展示策略名时，顶栏只留选股日，避免同一截断文案出现两遍 -->
    <el-tooltip v-if="parsed.date || parsed.title" :content="parsed.full" placement="bottom" :show-after="200">
      <span class="batch-rail__chip mono" tabindex="0">
        <template v-if="parsed.date">选股 {{ parsed.date }}</template>
        <template v-else>{{ parsed.title }}</template>
      </span>
    </el-tooltip>
  </div>
</template>

<style scoped>
.batch-rail__stepper {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  padding: 0 var(--gap-1);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.batch-rail__pos {
  min-width: 2.6rem;
  text-align: center;
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  font-weight: 600;
}

.batch-rail__chip {
  font-size: var(--fs-kicker);
  font-weight: 600;
  color: var(--ink);
  padding: 0 var(--gap-1);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  font-variant-numeric: tabular-nums;
  cursor: default;
  max-width: 11rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .batch-rail { flex: 1 1 100%; margin-left: 0; }
  .batch-rail__chip {
    max-width: 8.5rem;
  }
}
</style>
