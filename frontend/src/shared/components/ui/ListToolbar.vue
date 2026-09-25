<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, type Component } from 'vue'
import { Download, Plus, Trash2, Upload } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'

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
  batchDelete: { label: '批量删除', icon: Trash2, kind: 'danger' },
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

/** 破坏性批量操作走印章红描边；其余保持中性，主操作才是实心主色 */
function variantOf(kind: Preset['kind']) {
  if (kind === 'primary') return 'default' as const
  if (kind === 'danger') return 'destructive' as const
  return 'outline' as const
}
</script>

<template>
  <div class="inline-flex flex-wrap items-center gap-2">
    <Button
      v-for="action in visible"
      :key="action.key"
      type="button"
      size="sm"
      :variant="variantOf(action.kind)"
      :disabled="action.disabled || action.loading"
      class="m-0"
      @click="action.onClick()"
    >
      <Spinner v-if="action.loading" class="animate-spin" aria-hidden="true" />
      <component :is="action.icon" v-else aria-hidden="true" />
      {{ action.label }}
    </Button>
    <slot />
  </div>
</template>
