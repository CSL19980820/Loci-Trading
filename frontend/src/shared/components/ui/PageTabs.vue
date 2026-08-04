<script setup lang="ts">
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
    ariaLabel?: string
  }>(),
  {
    sticky: true,
    dense: false,
    ariaLabel: '页面分区',
  },
)

const emit = defineEmits<{
  'update:modelValue': [string]
}>()

function onUpdate(name: string | number): void {
  const key = String(name)
  const item = props.items.find((entry) => entry.name === key)
  if (!item || item.disabled) return
  if (key !== props.modelValue) emit('update:modelValue', key)
}
</script>

<template>
  <div
    class="page-tabs"
    :class="{ 'page-tabs--sticky': sticky, 'page-tabs--dense': dense }"
  >
    <el-tabs
      class="page-tabs__el"
      :model-value="modelValue"
      :aria-label="ariaLabel"
      @update:model-value="onUpdate"
    >
      <el-tab-pane
        v-for="item in items"
        :key="item.name"
        :name="item.name"
        :disabled="item.disabled"
      >
        <template #label>
          <span class="page-tabs__label">{{ item.label }}</span>
          <span v-if="item.badge != null && item.badge !== ''" class="page-tabs__badge">{{
            item.badge
          }}</span>
        </template>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.page-tabs {
  --page-tabs-sticky-top: 0px;
  --el-tabs-header-height: 2.35rem;
  margin: 0 0 0.75rem;
  padding: 0 0.85rem;
  background: var(--paper);
}

.page-tabs--sticky {
  position: sticky;
  top: var(--page-tabs-sticky-top);
  z-index: 5;
  margin-left: 0;
  margin-right: 0;
  box-shadow: 0 1px 0 var(--rule);
}

.page-tabs--dense {
  --el-tabs-header-height: 2rem;
  margin-bottom: 0.55rem;
}

.page-tabs__el :deep(.el-tabs__header) {
  margin: 0;
}

.page-tabs__el :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: var(--rule);
}

.page-tabs__el :deep(.el-tabs__item) {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0 0.9rem;
  color: var(--mist);
  font: 500 0.9rem/1.25 var(--font);
  letter-spacing: 0.02em;
}

.page-tabs--dense .page-tabs__el :deep(.el-tabs__item) {
  padding: 0 0.7rem;
  font-size: 0.84rem;
}

.page-tabs__el :deep(.el-tabs__item:hover) {
  color: var(--ink);
}

.page-tabs__el :deep(.el-tabs__item.is-active) {
  color: var(--ink);
  font-weight: 650;
}

.page-tabs__el :deep(.el-tabs__active-bar) {
  height: 2px;
  background-color: var(--seal);
  border-radius: 1px;
}

.page-tabs__el :deep(.el-tabs__content) {
  display: none;
}

.page-tabs__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.1rem;
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
  background: var(--sheet);
  border: 1px solid var(--rule);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 0.68rem;
  font-weight: 600;
  line-height: 1.2;
}

.page-tabs__el :deep(.el-tabs__item.is-active) .page-tabs__badge {
  border-color: color-mix(in srgb, var(--seal) 35%, var(--rule));
  background: var(--seal-soft);
  color: var(--seal-ink);
}
</style>
