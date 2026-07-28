<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { BoardBucket, UniversePreset, UniverseStats } from '@/shared/types/quant'

defineProps<{
  universePreset: string
  universeBoards: BoardBucket[]
  excludeSt: boolean
  universePresets: UniversePreset[]
  universeStats: UniverseStats | null
  previewCount: number | null
  previewFunnelText: string
  busy: boolean
}>()

const emit = defineEmits<{
  'update:universePreset': [string]
  'update:universeBoards': [BoardBucket[]]
  'update:excludeSt': [boolean]
  applyPreset: [id: string]
  boardsChange: [values: string[] | BoardBucket[]]
  excludeStChange: []
  previewPool: []
}>()
</script>

<template>
  <Sheet title="股票范围" class="mb" margin>
    <div class="universe-bar">
      <el-select
        :model-value="universePreset"
        style="width: 14rem"
        @update:model-value="emit('update:universePreset', $event)"
        @change="emit('applyPreset', $event)"
      >
        <el-option
          v-for="item in universePresets"
          :key="item.id"
          :label="item.label"
          :value="item.id"
        />
      </el-select>
      <el-checkbox-group
        :model-value="universeBoards"
        @update:model-value="emit('update:universeBoards', $event as BoardBucket[])"
        @change="emit('boardsChange', $event)"
      >
        <el-checkbox value="main" label="主板" />
        <el-checkbox value="chi_next" label="创业板" />
        <el-checkbox value="star" label="科创板" />
      </el-checkbox-group>
      <el-checkbox
        :model-value="excludeSt"
        @update:model-value="emit('update:excludeSt', Boolean($event))"
        @change="emit('excludeStChange')"
      >
        剔除 ST
      </el-checkbox>
      <el-button size="small" :disabled="busy" @click="emit('previewPool')">预览池</el-button>
      <span v-if="previewCount !== null" class="muted mono">约 {{ previewCount }} 只</span>
      <span v-if="previewFunnelText" class="muted mono">{{ previewFunnelText }}</span>
      <span v-if="universeStats" class="muted">北交所已屏蔽 · 库内 ST {{ universeStats.st_count }}</span>
    </div>
    <p class="form-hint">
      默认主板+创业+科创，剔除 ST/*ST；北交所不进入选股。范围作用于选股与回测。
    </p>
  </Sheet>
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}
.universe-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1rem;
}
.universe-bar :deep(.el-checkbox) {
  margin-right: 0;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}
.universe-bar :deep(.el-checkbox.is-checked) {
  border-color: var(--seal);
  background: var(--seal-soft);
}
</style>
