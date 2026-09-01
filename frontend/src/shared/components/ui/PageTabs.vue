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
    <div class="page-tabs__row">
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
      <div v-if="$slots.trailing" class="page-tabs__trailing">
        <slot name="trailing" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-tabs {
  --page-tabs-sticky-top: 0px;
  /* 分区条就是一条 28px 的控件行，不是导航横幅 */
  --el-tabs-header-height: var(--ctl-h);
  margin: 0 0 var(--gap-2);
  padding: 0 var(--pad-sheet-x);
  background: var(--paper);
}

.page-tabs__row {
  display: flex;
  align-items: center;
  gap: var(--gap-3);
  min-width: 0;
}

.page-tabs__el {
  flex: 1 1 auto;
  min-width: 0;
}

.page-tabs__trailing {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  color: var(--mist);
  font: var(--fs-aux) / 1.4 var(--mono);
  white-space: nowrap;
}

.page-tabs--sticky {
  position: sticky;
  top: var(--page-tabs-sticky-top);
  z-index: 5;
  margin-left: 0;
  margin-right: 0;
  border-bottom: 1px solid var(--rule);
}

.page-tabs--dense {
  --el-tabs-header-height: var(--row-h-sm);
  margin-bottom: var(--gap-1);
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
  gap: var(--gap-1);
  padding: 0 var(--gap-3);
  color: var(--mist);
  font: 500 var(--fs-body) / 1.25 var(--font);
  letter-spacing: 0.03em;
}

.page-tabs--dense .page-tabs__el :deep(.el-tabs__item) {
  padding: 0 var(--gap-2);
  font-size: var(--fs-aux);
}

.page-tabs__el :deep(.el-tabs__item:hover) {
  color: var(--ink);
}

.page-tabs__el :deep(.el-tabs__item.is-active) {
  color: var(--ink);
  font-weight: 700;
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
  min-width: var(--gap-4);
  padding: 0 var(--gap-1);
  border-radius: var(--radius);
  background: var(--sheet);
  border: 1px solid var(--rule);
  color: var(--muted);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  line-height: 1.4;
}

.page-tabs__el :deep(.el-tabs__item.is-active) .page-tabs__badge {
  border-color: color-mix(in srgb, var(--seal) 35%, var(--rule));
  background: var(--seal-soft);
  color: var(--seal-ink);
}
</style>
