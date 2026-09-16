<script setup lang="ts">
/**
 * PageToolbar —— 路由页顶部**唯一**的一条功能行，取代已下线的 PageHeader。
 *
 * 为什么没有标题：页面身份已经由侧栏高亮的菜单项交代完了。在正文顶上再印一遍
 * 「候选池」「复盘中心」，既不导航也不操作，纯占一整行版面——这正是要删掉的东西。
 * 页头存在的意义只剩三件：**筛选、读数、操作**，全部压进这一行。
 *
 * 槽位（从左到右）：
 *   default —— 筛选控件 / 分段切换 / 面包屑，左对齐
 *   stats  —— 行内读数（配 HeaderStat），自动推到右边
 *   actions —— 操作按钮，最右
 *
 * `note` 是口径提示：**不占版面**，只在最右渲染一枚 12px 的 ⓘ，全文进 tooltip。
 * 需要整段说明的一律进 docs，不要塞回界面（见 docs/ui-spec.md 文案规范）。
 *
 * 放在 .page-fill 内、.page-scroll 外，随页固定不滚。
 */
import { InfoFilled } from '@element-plus/icons-vue'

withDefaults(
  defineProps<{
    /** 一句口径说明；只渲染成一枚 ⓘ，全文在 tooltip 里 */
    note?: string
    /** 紧凑档：给 Tab 页或次级页用 */
    dense?: boolean
    /** 去掉底部 hairline：下面紧跟 PageTabs / filter-bar 时避免双线 */
    seamless?: boolean
  }>(),
  { dense: false, seamless: false },
)
</script>

<template>
  <!-- 路由页顶部唯一功能行：筛选/读数/操作压进一行，随页固定不滚。note 只渲染一枚 ⓘ -->
  <div
    class="page-toolbar border-line bg-surface flex min-w-0 min-h-[calc(var(--ctl-h)+var(--gap-2))] flex-shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b px-[var(--pad-sheet-x)] py-2"
    :class="{ 'page-toolbar--dense min-h-[var(--ctl-h)] !py-1': dense, 'page-toolbar--seamless border-b-0': seamless }"
  >
    <div v-if="$slots.default" class="page-toolbar__filters flex min-w-0 max-w-full flex-wrap items-center gap-x-2 gap-y-1">
      <slot />
    </div>

    <div v-if="$slots.stats" class="page-toolbar__stats ml-auto flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <slot name="stats" />
    </div>

    <div v-if="$slots.actions" class="page-toolbar__actions flex min-w-0 flex-wrap items-center gap-2" :class="{ 'ml-auto': !$slots.stats }">
      <slot name="actions" />
    </div>
    <el-tooltip
      v-if="note"
      :content="note"
      placement="bottom-end"
      :show-after="200"
    >
      <el-button text circle class="page-toolbar__note text-mist" :class="{ 'ml-auto': !$slots.default && !$slots.stats && !$slots.actions }" aria-label="口径说明">
        <el-icon><InfoFilled /></el-icon>
      </el-button>
    </el-tooltip>
  </div>
</template>

<style scoped>
.page-toolbar {
  border-radius: var(--radius) var(--radius) 0 0;
}
.page-toolbar__filters > :deep(*) {
  max-width: 100%;
}
.page-toolbar__note.el-button {
  width: var(--ctl-h);
  margin: 0;
}
@media (max-width: 640px) {
  .page-toolbar { padding-inline: var(--gap-2); }
  .page-toolbar__filters { flex: 1 1 100%; }
  .page-toolbar__stats { margin-inline-start: 0; }
  .page-toolbar__actions { margin-inline-start: auto; }
}
</style>
