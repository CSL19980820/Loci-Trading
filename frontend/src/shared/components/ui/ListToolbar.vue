<script setup lang="ts">
import { computed, type Component } from 'vue'
import { Delete, Download, Plus, Upload } from '@element-plus/icons-vue'

/** 列表工具栏固定键（文案/图标钉死） */
export type ListToolbarKey = 'create' | 'batchDelete' | 'import' | 'export'

/** 单项：传对象即显示；`false` / 不写 = 隐藏 */
export type ListToolbarItemConfig = {
  /** 默认 true；显式 false 可临时隐藏但仍保留配置 */
  show?: boolean
  onClick: () => void
  loading?: boolean
  disabled?: boolean
}

export type ListToolbarConfig = Partial<Record<ListToolbarKey, ListToolbarItemConfig | false>>

type Preset = {
  label: string
  icon: Component
  kind: 'primary' | 'danger' | 'default'
}

const PRESETS: Record<ListToolbarKey, Preset> = {
  create: { label: '新增', icon: Plus, kind: 'primary' },
  batchDelete: { label: '批量删除', icon: Delete, kind: 'danger' },
  import: { label: '导入', icon: Upload, kind: 'default' },
  export: { label: '导出', icon: Download, kind: 'default' },
}

const ORDER: ListToolbarKey[] = ['create', 'batchDelete', 'import', 'export']

const props = withDefaults(
  defineProps<{
    /** 按键配置显隐与回调；未出现的键不渲染 */
    config?: ListToolbarConfig
  }>(),
  { config: () => ({}) },
)

type VisibleItem = ListToolbarItemConfig & Preset & { key: ListToolbarKey }

const visible = computed(() => {
  const out: VisibleItem[] = []
  for (const key of ORDER) {
    const raw = props.config[key]
    if (typeof raw !== 'object' || raw === null) continue
    if (raw.show === false) continue
    out.push({ key, ...PRESETS[key], ...raw })
  }
  return out
})

function buttonType(kind: Preset['kind']): '' | 'primary' | 'danger' {
  if (kind === 'primary') return 'primary'
  if (kind === 'danger') return 'danger'
  return ''
}
</script>

<template>
  <div class="inline-flex flex-wrap items-center gap-2">
    <el-button
      v-for="action in visible"
      :key="action.key"
      size="small"
      :type="buttonType(action.kind)"
      :plain="action.kind === 'danger'"
      :icon="action.icon"
      :loading="action.loading"
      :disabled="action.disabled"
      class="m-0"
      @click="action.onClick()"
    >
      {{ action.label }}
    </el-button>
    <slot />
  </div>
</template>
