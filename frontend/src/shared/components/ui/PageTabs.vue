<script setup lang="ts">
import { computed } from 'vue'

import { Tabs, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'

export type PageTabItem = {
  name: string
  label: string
  badge?: string | number
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    items: PageTabItem[]
    /** 吸顶；短页可关 */
    sticky?: boolean
    /** 多标签（如设置 9 项）更紧、可横滑 */
    dense?: boolean
    /** pill = 药片分段（用于面板内二级切换）；默认 underline = 下划线（页级分区） */
    variant?: 'underline' | 'pill'
    ariaLabel?: string
  }>(),
  {
    sticky: true,
    dense: false,
    variant: 'underline',
    ariaLabel: '页面分区',
  },
)

const emit = defineEmits<{
  'update:modelValue': [string]
}>()

/**
 * 分区只切「值」，不渲染面板：面板由父级用 `v-show` 编排（切 Tab 不重建表格、不丢滚动位置）。
 * 只保留 reka `Tabs` 的 tablist / tab 语义与方向键导航，刻意不挂 `TabsContent`。
 */
const value = computed({
  get: () => props.modelValue,
  set: (next: string | number) => {
    const key = String(next)
    const item = props.items.find((entry) => entry.name === key)
    if (!item || item.disabled) return
    if (key !== props.modelValue) emit('update:modelValue', key)
  },
})
</script>

<template>
  <div
    class="page-tabs"
    :class="[
      `page-tabs--${variant}`,
      { 'page-tabs--sticky': sticky, 'page-tabs--dense': dense },
    ]"
  >
    <div class="page-tabs__row">
      <Tabs v-model="value" class="page-tabs__tabs">
        <TabsList class="page-tabs__list" :aria-label="ariaLabel">
          <TabsTrigger
            v-for="item in items"
            :key="item.name"
            :value="item.name"
            :disabled="item.disabled"
            class="page-tabs__item"
          >
            <span class="page-tabs__label">{{ item.label }}</span>
            <span v-if="item.badge != null && item.badge !== ''" class="page-tabs__badge">{{ item.badge }}</span>
          </TabsTrigger>
        </TabsList>
      </Tabs>
      <div v-if="$slots.trailing" class="page-tabs__trailing">
        <slot name="trailing" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-tabs {
  margin-bottom: var(--workspace-gap, 5px);
  flex-shrink: 0;
  min-width: 0;
}

.page-tabs--sticky {
  position: sticky;
  top: var(--page-tabs-sticky-top, 0px);
  z-index: var(--z-sticky);
  background: color-mix(in oklab, var(--surface-canvas) 88%, transparent);
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
}

.page-tabs__row {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-3);
}

.page-tabs__tabs {
  min-width: 0;
  flex: 1 1 auto;
  gap: 0;
}

/* 列表本体：透明、无圆角、可横滑，不显示滚动条 */
.page-tabs__list {
  display: flex;
  justify-content: flex-start;
  width: 100%;
  height: auto;
  padding: 0;
  gap: 0;
  border-radius: 0;
  background: transparent;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}

.page-tabs__list::-webkit-scrollbar {
  display: none;
}

.page-tabs__item {
  position: relative;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 var(--gap-3);
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: var(--text-tertiary);
  font: 500 var(--fs-ui) / 1.25 var(--font);
  white-space: nowrap;
  transition: color var(--dur-fast) var(--ease);
}

.page-tabs--dense .page-tabs__item {
  height: 36px;
  padding: 0 10px;
}

.page-tabs__item:hover {
  background: transparent;
  box-shadow: none;
  color: var(--text-primary);
}

/* 悬停时在文字后面浮起一片淡底（Vercel 式），不占布局 */
.page-tabs__item::before {
  content: '';
  position: absolute;
  inset: 6px 2px;
  border-radius: var(--radius-sm);
  background: var(--surface-hover);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
  z-index: -1;
}

.page-tabs__item:hover::before {
  opacity: 1;
}

/* 下划线指示器 */
.page-tabs--underline .page-tabs__item::after {
  content: '';
  position: absolute;
  right: var(--gap-3);
  bottom: -1px;
  left: var(--gap-3);
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--seal);
  opacity: 0;
  transform: scaleX(0.6);
  transition:
    opacity var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}

.page-tabs--dense.page-tabs--underline .page-tabs__item::after {
  right: 10px;
  left: 10px;
}

.page-tabs--underline .page-tabs__item[data-state='active'] {
  background: transparent;
  box-shadow: none;
  color: var(--text-primary);
  font-weight: 600;
}

.page-tabs--underline .page-tabs__item[data-state='active']::after {
  opacity: 1;
  transform: scaleX(1);
}

.page-tabs--underline .page-tabs__list {
  border-bottom: 1px solid var(--border-subtle);
}

/* 药片式：用于面板里二级切换 */
.page-tabs--pill .page-tabs__list {
  width: fit-content;
  max-width: 100%;
  padding: 3px;
  border-radius: var(--radius);
  background: var(--surface-sunken);
  gap: 2px;
}

.page-tabs--pill .page-tabs__item {
  height: 28px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-aux);
}

.page-tabs--pill .page-tabs__item::before {
  display: none;
}

.page-tabs--pill .page-tabs__item:hover {
  color: var(--text-primary);
}

.page-tabs--pill .page-tabs__item[data-state='active'] {
  background: var(--surface);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: var(--shadow-xs);
}

.page-tabs__item:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
  border-radius: var(--radius-sm);
}

.page-tabs__label {
  min-width: 0;
}

.page-tabs__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  transition: all var(--dur-fast) var(--ease);
}

.page-tabs__item[data-state='active'] .page-tabs__badge {
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.page-tabs__trailing {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
}

@media (max-width: 640px) {
  .page-tabs__row {
    flex-wrap: wrap;
  }

  .page-tabs__trailing {
    display: none;
  }
}
</style>
