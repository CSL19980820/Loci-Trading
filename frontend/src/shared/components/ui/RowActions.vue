<script setup lang="ts">
import { computed } from 'vue'

export interface RowAction {
  key: string
  label: string
  type?: 'primary' | 'danger' | 'success' | 'warning' | 'info'
  divided?: boolean
  /** 置灰但保留在原位：动作消失会让行与行的操作列错位，也让用户以为「没这个功能」 */
  disabled?: boolean
  /** 置灰的原因（≤14 字）。只在 disabled 时挂 tooltip，正常态不打扰 */
  tip?: string
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
  const action = extra.value.find((item) => item.key === key)
  if (!action || action.disabled) return
  action.onClick()
}
</script>

<template>
  <div class="inline-flex flex-nowrap items-center justify-end gap-0 whitespace-nowrap" @click.stop>
    <el-tooltip
      v-for="action in primary"
      :key="action.key"
      :content="action.tip || ''"
      :disabled="!action.disabled || !action.tip"
      placement="top"
      :show-after="200"
    >
      <span class="inline-flex items-center">
        <el-button
          text
          :type="action.type || 'primary'"
          size="small"
          :disabled="action.disabled"
          class="m-0 px-1"
          @click="action.onClick"
        >
          {{ action.label }}
        </el-button>
      </span>
    </el-tooltip>
    <el-dropdown v-if="extra.length" trigger="click" @command="onMore">
      <el-button text size="small">更多</el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="action in extra"
            :key="action.key"
            :command="action.key"
            :divided="action.divided"
            :disabled="action.disabled"
          >
            {{ action.label }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
/* 行内删除类动作同样走印章红，不借 EP 默认 danger 的橙红 */
.inline-flex :deep(.el-button) {
  margin: 0;
}
.inline-flex :deep(.el-button--danger.is-text) {
  --el-button-text-color: var(--stamp);
  --el-button-hover-text-color: var(--stamp);
  --el-button-hover-bg-color: color-mix(in oklab, var(--stamp) 8%, transparent);
}
</style>
