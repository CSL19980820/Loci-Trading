<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'

/**
 * 设置分区壳（Raycast Settings 的右侧内容列）。
 *
 * 结构：单行状态回执与操作（导航已提供分区名称）
 * → 内容列 → 可选的粘底操作栏。整列限宽 880px，与左栏一起坐在画布上；卡片由各分区自己分组。
 * `fill` 给名册型分区（表格 / 卡片网格）：body 吃满剩余高度并自己滚。
 */
export type ReceiptPair = {
  key: string
  value: string
  hint?: string
  /**
   * 有 `onClick` 的回执项渲染成可点的链接。
   * 回执上写着「上次失败 3」却点不动，等于把线索摆出来又让人自己去找那条 run。
   */
  onClick?: () => void
}

withDefaults(
  defineProps<{
    title: string
    /** 页头下的一句描述 */
    description?: string
    /** 标题旁的静默状态（非导航） */
    receipt?: ReceiptPair[]
    /** @deprecated 表单不再限宽；保留 prop 以免旧调用报错 */
    form?: boolean
    /** 名册型：body 吃满剩余高度 */
    fill?: boolean
  }>(),
  {
    description: '',
    receipt: () => [],
    form: false,
    fill: false,
  },
)
</script>

<template>
  <section
    :aria-label="title"
    class="settings-panel"
    :class="{ 'settings-panel--fill': fill }"
  >
    <header v-if="receipt.length || $slots.action" class="settings-panel__head">
        <dl v-if="receipt.length" class="settings-panel__receipt" aria-label="状态回执">
          <div v-for="pair in receipt" :key="pair.key" class="settings-panel__pair" :title="pair.hint">
            <dt>{{ pair.key }}</dt>
            <dd>
              <Button
                v-if="pair.onClick"
                variant="link"
                class="settings-panel__pair-link"
                @click="pair.onClick()"
              >
                {{ pair.value }}
              </Button>
              <template v-else>{{ pair.value }}</template>
            </dd>
          </div>
        </dl>
      <div v-if="$slots.action" class="settings-panel__actions"><slot name="action" /></div>
    </header>
    <div class="settings-panel__body">
      <slot />
    </div>
    <footer v-if="$slots.foot" class="settings-panel__foot">
      <slot name="foot" />
    </footer>
  </section>
</template>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  flex: 1 0 auto;
  width: 100%;
  max-width: 880px;
  min-width: 0;
  /* 内容比视口高时整列跟着 .ops-pane 滚，不在这一层截断 */
  min-height: 100%;
}

.settings-panel__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-left: auto; max-width: 100%; }

.settings-panel__head {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px;
  padding-top: var(--gap-1);
  padding-bottom: var(--gap-3);
}

.settings-panel__receipt {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  min-width: 0;
}

.settings-panel__pair {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  min-width: 0;
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1;
  white-space: nowrap;
}

.settings-panel__pair dt {
  color: var(--text-tertiary);
}

.settings-panel__pair dd {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary);
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.settings-panel__pair-link {
  height: auto;
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: var(--stamp);
  text-decoration: underline dotted;
  text-underline-offset: 0.2em;
}

.settings-panel__pair-link:hover,
.settings-panel__pair-link:focus-visible {
  text-decoration-style: solid;
}

.settings-panel__body {
  display: flex;
  flex-direction: column;
  gap: var(--gap-4);
  flex: 1 0 auto;
  min-width: 0;
  width: 100%;
  padding-bottom: var(--gap-6);
}

/* 列里的卡片不许被压扁：高度不够就整列滚动 */
.settings-panel__body > * {
  flex-shrink: 0;
}

.settings-panel--fill {
  flex: 1 1 auto;
  max-width: none;
  min-height: 0;
  height: 100%;
}

/* 名册型：body 吃满剩余高度并自己滚，主体区（如 jobs-layout）允许收缩 */
.settings-panel--fill .settings-panel__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  padding-bottom: 0;
}

.settings-panel--fill .settings-panel__body > * {
  flex-shrink: 1;
}

/* 粘底操作栏：毛玻璃底，跟随内容列滚动到底部时贴住 */
.settings-panel__foot {
  position: sticky;
  bottom: 0;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-2);
  justify-content: flex-end;
  align-items: center;
  margin-top: auto;
  padding: var(--gap-3) 0;
  border-top: 1px solid var(--border-subtle);
  background: color-mix(in oklab, var(--surface-canvas) 88%, transparent);
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
}

@media (max-width: 640px) {
  .settings-panel__foot {
    padding: var(--gap-2) 0;
  }

  .settings-panel__foot :deep(button) {
    min-height: 40px;
  }
}
</style>
