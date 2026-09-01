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
  <div
    class="page-toolbar"
    :class="{ 'page-toolbar--dense': dense, 'page-toolbar--seamless': seamless }"
  >
    <div v-if="$slots.default" class="page-toolbar__lead">
      <slot />
    </div>

    <div v-if="$slots.stats" class="page-toolbar__stats">
      <slot name="stats" />
 </div>

    <div v-if="$slots.actions" class="page-toolbar__actions">
      <slot name="actions" />
      <el-tooltip v-if="note" :content="note" placement="bottom-end" :show-after="200">
        <el-icon class="page-toolbar__note" tabindex="0" :aria-label="note"><InfoFilled /></el-icon>
      </el-tooltip>
    </div>
  <el-tooltip
      v-else-if="note"
      :content="note"
      placement="bottom-end"
      :show-after="200"
    >
      <el-icon class="page-toolbar__note page-toolbar__note--solo" tabindex="0" :aria-label="note">
        <InfoFilled />
      </el-icon>
</el-tooltip>
  </div>
</template>

<style scoped>
.page-toolbar {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  min-height: calc(var(--ctl-h) + var(--gap-2));
  padding: var(--gap-1) var(--pad-sheet-x);
  border-bottom: 1px solid var(--rule);
  background: var(--sheet);
}

.page-toolbar--dense {
  min-height: var(--ctl-h);
  padding-block: 0;
}

/* 下面紧跟 PageTabs / filter-bar 时，两条 hairline 会叠成一道脏边 */
.page-toolbar--seamless {
  border-bottom: 0;
}

.page-toolbar__lead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  min-width: 0;
}

/* 读数与操作一起靠右；只有读数时它自己吃掉 auto margin */
.page-toolbar__stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-3);
  min-width: 0;
  margin-left: auto;
}

.page-toolbar__actions {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin-left: auto;
}

/* 读数在场时，操作区紧跟其后，不再各自抢 auto margin */
.page-toolbar__stats + .page-toolbar__actions {
  margin-left: 0;
}

/* 口径提示：一枚 ⓘ，不占文本宽度 */
.page-toolbar__note {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
  cursor: help;
}

.page-toolbar__note:hover {
  color: var(--muted);
}

.page-toolbar__note--solo {
  margin-left: auto;
}

.page-toolbar__note:focus-visible {
outline: 2px solid var(--seal);
  outline-offset: 2px;
  border-radius: var(--radius);
}
</style>
