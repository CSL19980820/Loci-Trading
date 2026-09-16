<script setup lang="ts">
import UiCard from '@/shared/components/ui/UiCard.vue'
import UiCardContent from '@/shared/components/ui/UiCardContent.vue'
import UiCardFooter from '@/shared/components/ui/UiCardFooter.vue'
import UiCardHeader from '@/shared/components/ui/UiCardHeader.vue'
import UiCardTitle from '@/shared/components/ui/UiCardTitle.vue'
export type ReceiptPair = {
  key: string
  value: string
  hint?: string
  /**
   * 有 `onClick` 的回执项渲染成可点的链接。
   *
   * 回执上写着「上次失败 3」却点不动，等于把线索摆出来又让人自己去找那条 run。
   * 只给真的能跳过去的项加，别把静默状态做成一排假按钮。
   */
  onClick?: () => void
}

withDefaults(
  defineProps<{
    title: string
    /** 标题旁的静默状态（非导航） */
    receipt?: ReceiptPair[]
    /** @deprecated 表单不再限宽；保留 prop 以免旧调用报错 */
    form?: boolean
    /** 名册型：body 吃满剩余高度 */
    fill?: boolean
  }>(),
  {
    receipt: () => [],
    form: false,
    fill: false,
  },
)
</script>

<template>
  <UiCard
    :aria-label="title"
    class="settings-panel"
    :class="{ 'settings-panel--fill': fill }"
  >
    <!--
      标题保留（不是冗余）：≤900px 时 OpsView 把 rail 整条 `display:none` 塌成单列，
      左侧「rail 高亮即身份」当场消失；而且这个壳还被 `/quant?tab=jobs` 的 JobsTab
      复用——那条路由压根没有 rail。删了就有两处失去身份。
      代价压到最低：整个 head 恒为一行（标题 + 回执读数 + 主操作），回执超长省略。
    -->
    <UiCardHeader class="settings-panel__head">
      <UiCardTitle class="settings-panel__title">{{ title }}</UiCardTitle>
      <template #action>
        <p v-if="receipt.length" class="settings-panel__receipt" aria-label="状态回执">
          <template v-for="(pair, i) in receipt" :key="pair.key">
            <span v-if="i > 0" class="mx-1" aria-hidden="true">·</span>
            <el-button
              v-if="pair.onClick"
              link
              class="settings-panel__pair settings-panel__pair--link"
              :title="pair.hint"
              @click="pair.onClick()"
            >
              <span class="text-mist">{{ pair.key }}</span>
              {{ pair.value }}
            </el-button>
            <span v-else :title="pair.hint">
              <span class="text-mist">{{ pair.key }}</span>
              {{ pair.value }}
            </span>
          </template>
        </p>
        <slot name="action" />
      </template>
    </UiCardHeader>
    <UiCardContent :padded="false" class="settings-panel__body">
      <slot />
    </UiCardContent>
    <UiCardFooter v-if="$slots.foot" class="settings-panel__foot">
      <slot name="foot" />
    </UiCardFooter>
  </UiCard>
</template>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  height: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--surface);
}

/* 恒为单行：标题 + 回执 + 主操作。回执让位（省略号），按钮永不换行下去 */
.settings-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  background: var(--surface-sunken);
  flex-shrink: 0;
  border-bottom: 1px solid var(--rule);
}

.settings-panel__title {
  margin: 0;
  flex: 0 0 auto;
  font-family: var(--font-sans);
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--ink);
  letter-spacing: 0.03em;
  line-height: 1.2;
}

.settings-panel__receipt {
  margin: 0;
  min-width: 0;
  flex: 1 1 auto;
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 同 LiveStatusBar：分隔点走文字层令牌，不用为 1px 线校准的 --rule */
.settings-panel__sep {
  margin: 0 var(--gap-1);
  color: var(--text-disabled);
}

.settings-panel__pair {
  white-space: nowrap;
}

/* el-button link 自带 14px/500 与内边距，回执行要它退回等宽小字 */
.settings-panel__pair--link.el-button {
  height: auto;
  padding: 0;
  font: inherit;
  vertical-align: baseline;
  text-decoration: underline dotted;
  text-underline-offset: 0.2em;
  --el-button-text-color: inherit;
  --el-button-hover-text-color: var(--seal-ink);
  --el-button-active-text-color: var(--seal-ink);
}

.settings-panel__pair--link.el-button:hover,
.settings-panel__pair--link.el-button:focus-visible {
  text-decoration-style: solid;
}

.settings-panel__k {
  color: var(--mist);
  margin-right: var(--gap-1);
}

.settings-panel__action {
  margin-left: auto;
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 0.35rem;
  flex: 0 0 auto;
}

.settings-panel__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: var(--gap-3);
  overscroll-behavior: contain;
  width: 100%;
}

.settings-panel--fill .settings-panel__body {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
}

.settings-panel__foot {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-2);
  justify-content: flex-end;
  align-items: center;
  padding: var(--gap-2) var(--gap-3);
  border-top: 1px solid var(--rule);
  flex-shrink: 0;
  width: 100%;
}

/* 窄屏也不换行：回执自己省略，标题与按钮始终在同一行上 */
@media (max-width: 720px) {
  .settings-panel__head {
    gap: var(--gap-1) var(--gap-2);
  }
}
</style>
