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
  <!-- 分区条=28px控件行。sticky 让它贴在 scroll 顶；badge 是等宽计数 -->
  <div
    class="page-tabs bg-canvas mx-0 mb-2 shrink-0 px-[var(--pad-sheet-x)]"
    :class="sticky ? 'page-tabs--sticky sticky top-[var(--page-tabs-sticky-top,0px)] z-[var(--z-sticky)] border-b border-[var(--rule)]' : ''"
  >
    <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
      <el-tabs
        class="min-w-0 flex-auto"
        :model-value="modelValue"
        :aria-label="ariaLabel"
        :class="dense ? '[--el-tabs-header-height:var(--row-h-sm)]' : '[--el-tabs-header-height:var(--ctl-h)]'"
        @update:model-value="onUpdate"
      >
        <el-tab-pane
          v-for="item in items"
          :key="item.name"
          :name="item.name"
          :disabled="item.disabled"
        >
          <template #label>
            <span>{{ item.label }}</span>
            <span v-if="item.badge != null && item.badge !== ''" class="border-line bg-surface text-mist ml-1 inline-flex min-w-4 items-center justify-center rounded border px-1 font-mono text-[length:var(--fs-kicker)] leading-[1.4] font-semibold tabular-nums">{{
              item.badge
            }}</span>
          </template>
        </el-tab-pane>
      </el-tabs>
      <div v-if="$slots.trailing" class="page-tabs__trailing text-mist flex flex-none flex-wrap items-center gap-2 font-mono text-aux">
        <slot name="trailing" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 通过作用域深层选择器调整 EP 子组件，保留其键盘与溢出导航。 */
.min-w-0 :deep(.el-tabs__header) {
  margin: 0;
}
.min-w-0 :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: var(--rule);
}
.min-w-0 :deep(.el-tabs__item) {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  padding: 0 var(--gap-3);
  color: var(--mist);
  font: 500 var(--fs-body) / 1.25 var(--font);
  letter-spacing: 0.03em;
}
.min-w-0 :deep(.el-tabs__item:hover) {
  color: var(--ink);
}
.min-w-0 :deep(.el-tabs__item.is-active) {
  color: var(--seal-ink);
  font-weight: 700;
}
.min-w-0 :deep(.el-tabs__active-bar) {
  height: 2px;
  background-color: var(--seal);
  border-radius: 1px;
}
.min-w-0 :deep(.el-tabs__content) {
  display: none;
}
/* 选中态徽标：主色浅底+描边（D1：徽标不是价格，不上红绿） */
.min-w-0 :deep(.el-tabs__item.is-active) .border-line {
  border-color: color-mix(in oklab, var(--seal) 35%, var(--rule));
  background: var(--seal-soft);
  color: var(--seal-ink);
}
</style>
