<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
/**
 * 设置左栏（Raycast / Linear Settings 一路）。
 *
 * 透明底直接坐在画布上，不再自带卡片边框；每个分组一枚 11px kicker 标题，
 * 条目 32px 高，选中项是一枚**浮起的白色药片**（`--surface-raised` + `--shadow-xs`），
 * 左侧一颗状态点由摘要驱动，右侧等宽小字放读数（如 `LLM · 2 家`）。
 * 二级锚点常驻缩进在父项下，点一次直达该段。
 */
export type RailMark = 'ok' | 'idle' | 'bad'

/** 二级项：同一页里的锚点段，不换 tab，只滚过去。 */
export type SettingsRailAnchor = {
  label: string
  /** 目标元素 id（不带 #），与 SettingsSection 的 anchor 一致 */
  anchor: string
}

export type SettingsRailItem = {
  name: string
  label: string
  tail?: string
  state?: RailMark
  /** 页内锚点：「系统」页的数据目录 / 行情同步 / 推送 / 外观 四段 */
  children?: SettingsRailAnchor[]
}

export type SettingsRailGroup = {
  title: string
  items: SettingsRailItem[]
}

defineProps<{
  modelValue: string
  panelId: string
  groups: SettingsRailGroup[]
  /** 当前落在哪个锚点段（父层从路由 hash 传进来） */
  activeAnchor?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [string]
  'select-anchor': [anchor: string]
}>()

</script>

<template>
  <Tabs as="nav" :model-value="modelValue" orientation="vertical" class="settings-rail" aria-label="设置分区" @update:model-value="value => emit('update:modelValue', String(value))">
    <TabsList class="settings-rail__groups" aria-label="设置分区">
    <div
      v-for="group in groups"
      :key="group.title"
      class="settings-rail__group"
      role="presentation"
    >
      <h3 class="settings-rail__group-title">{{ group.title }}</h3>
      <div class="settings-rail__list">
        <template v-for="item in group.items" :key="item.name">
          <TabsTrigger :value="item.name" as-child>
          <Button access="read" variant="ghost"
            :id="`${panelId}-tab-${item.name}`"
            :aria-controls="panelId"
            type="button"
            class="settings-rail__item"
            :class="{ 'is-active': modelValue === item.name }"
            :title="[item.label, item.tail].filter(Boolean).join(' · ')"
            :data-name="item.name"
            :data-settings-rail="item.name"
          >
            <span
              class="settings-rail__mark"
              :class="`settings-rail__mark--${item.state || 'idle'}`"
              aria-hidden="true"
            />
            <span class="settings-rail__label">{{ item.label }}</span>
            <span
              v-if="item.tail"
              class="settings-rail__tail"
              :class="{ 'is-bad': item.state === 'bad' }"
            >{{ item.tail }}</span>
          </Button>
          </TabsTrigger>
          <div
            v-if="item.children?.length"
            class="settings-rail__anchors"
            role="group"
            :aria-label="`${item.label} · 分段`"
          >
            <Button access="read" variant="ghost"
              v-for="child in item.children"
              :key="child.anchor"
              type="button"
              class="settings-rail__anchor"
              :class="{ 'is-active': modelValue === item.name && activeAnchor === child.anchor }"
              :aria-current="modelValue === item.name && activeAnchor === child.anchor ? 'true' : undefined"
              :data-settings-anchor="child.anchor"
              @click="emit('select-anchor', child.anchor)"
            >
              {{ child.label }}
            </Button>
          </div>
        </template>
      </div>
    </div>
    </TabsList>
  </Tabs>
</template>

<style scoped>
.settings-rail__groups { display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start; gap: var(--gap-4); width: 100%; height: auto; padding: 0; background: transparent; }

.settings-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap-4);
  min-width: 0;
  min-height: 0;
  padding: var(--gap-1) var(--gap-2) var(--gap-4) 0;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.settings-rail__group-title {
  margin: 0 0 var(--gap-1);
  padding: 0 var(--gap-2);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.settings-rail__list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.settings-rail__item {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-width: 0;
  height: var(--ctl-h);
  margin: 0;
  padding: 0 var(--gap-2);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-ui);
  font-weight: 500;
  line-height: 1;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.settings-rail__item:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.settings-rail__item.is-active {
  border-color: var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: var(--shadow-xs);
}

.settings-rail__mark {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-strong);
}

.settings-rail__mark--ok {
  background: var(--ok);
}

.settings-rail__mark--bad {
  background: var(--warn);
}

.settings-rail__label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.settings-rail__tail {
  flex-shrink: 0;
  max-width: 45%;
  overflow: hidden;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 500;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-variant-numeric: tabular-nums;
}

.settings-rail__tail.is-bad {
  color: var(--warn);
}

/* 二级锚点：缩进展示归属，条目 28px */
.settings-rail__anchors {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 2px 0 var(--gap-1) 0;
  padding-left: var(--gap-5);
}

.settings-rail__anchor {
  display: flex;
  align-items: center;
  width: 100%;
  min-width: 0;
  height: var(--ctl-h-sm);
  margin: 0;
  padding: 0 var(--gap-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
  line-height: 1;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.settings-rail__anchor:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.settings-rail__anchor.is-active {
  color: var(--seal-ink);
  font-weight: 600;
}

.settings-rail__item:focus-visible,
.settings-rail__anchor:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}
</style>
