<script setup lang="ts">
import { computed } from 'vue'

export interface RowAction {
  key: string
  label: string
  type?: 'primary' | 'danger' | 'success' | 'warning' | 'info'
  divided?: boolean
  onClick: () => void
}

const props = withDefaults(
  defineProps<{
    actions: RowAction[]
    maxVisible?: number
  }>(),
  { maxVisible: 2 },
)

const primary = computed(() => props.actions.slice(0, props.maxVisible))
const extra = computed(() => props.actions.slice(props.maxVisible))

function onMore(key: string): void {
  extra.value.find((a) => a.key === key)?.onClick()
}
</script>

<template>
  <div class="row-actions" @click.stop>
    <el-button
      v-for="action in primary"
      :key="action.key"
      text
      :type="action.type || 'primary'"
      size="small"
      @click="action.onClick"
    >
      {{ action.label }}
    </el-button>
    <el-dropdown v-if="extra.length" trigger="click" @command="onMore">
      <el-button text size="small">更多</el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="action in extra"
            :key="action.key"
            :command="action.key"
            :divided="action.divided"
          >
            {{ action.label }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.row-actions :deep(.el-button) {
  margin: 0;
  padding-left: 0.35rem;
  padding-right: 0.35rem;
}

.row-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.row-actions :deep(.el-dropdown) {
  margin-left: 0;
}
</style>
