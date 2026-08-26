<script setup lang="ts">
/**
 * 账页页头 —— 全站路由页统一的开篇。
 *
 * 存在理由：此前多数页面打开就是「筛选条 + 大表」，没有标题、没有口径说明、
 * 没有主动作出口，用户进页不知道这页回答什么问题。页头用衬线标题承担仪式感，
 * 用一句 note 讲清口径，右侧收口关键读数与主操作。
 *
 * 放在 .page-fill 内、.page-scroll 外，随页固定不滚。
 */
withDefaults(
  defineProps<{
    title: string
    /** 标题右侧的轻量计数/状态，如「共 92 笔」 */
    count?: string | number
    /** 一句口径说明；讲「这页数字从哪来 / 是否只读」，不讲废话 */
    note?: string
    /** 紧凑档：给 Tab 页或次级页用 */
    dense?: boolean
  }>(),
  { dense: false },
)
</script>

<template>
  <header class="page-header" :class="{ 'page-header--dense': dense }">
    <div class="page-header__lead">
      <div class="page-header__titleline">
        <h1 class="page-header__title">{{ title }}</h1>
        <span v-if="count !== undefined && count !== ''" class="page-header__count">
          {{ count }}
        </span>
        <slot name="badge" />
      </div>
      <p v-if="note" class="page-header__note">{{ note }}</p>
    </div>

    <div v-if="$slots.stats" class="page-header__stats">
      <slot name="stats" />
    </div>

    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 1rem;
  padding: 0.7rem 0.95rem 0.6rem;
  border-bottom: 1px solid var(--rule);
  background: var(--sheet);
}

.page-header--dense {
  padding: 0.5rem 0.95rem 0.45rem;
}

.page-header__lead {
  flex: 1 1 14rem;
  min-width: 0;
}

.page-header__titleline {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem;
  min-width: 0;
}

.page-header__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--fs-hero);
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: 0.01em;
  color: var(--ink);
}

.page-header--dense .page-header__title {
  font-size: 1.2rem;
}

.page-header__count {
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
}

.page-header__note {
  margin: 0.2rem 0 0;
  font-size: var(--fs-aux);
  line-height: 1.45;
  color: var(--mist);
}

.page-header__stats {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 1.15rem;
  min-width: 0;
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-left: auto;
}

@media (max-width: 640px) {
  .page-header {
    padding-inline: 0.75rem;
  }

  .page-header__title {
    font-size: 1.2rem;
  }

  .page-header__actions {
    margin-left: 0;
  }
}
</style>
