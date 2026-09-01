<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import type { HealthCheckRow } from '@/features/review/composables/useHealthCheckup'

const props = defineProps<{
  issueRows: HealthCheckRow[]
  okRows: HealthCheckRow[]
  pendingRows: HealthCheckRow[]
  repairBusy: string
  showActions?: boolean
  selectedIds?: string[]
  /** 扫描中标题；idle 可传「待检」 */
  pendingTitle?: string
}>()

const emit = defineEmits<{
  repair: [row: HealthCheckRow]
  'update:selectedIds': [ids: string[]]
}>()

const router = useRouter()
const okOpen = ref(false)

const statusLabel: Record<HealthCheckRow['status'], string> = {
  pending: '待检',
  running: '扫描',
  ok: '通过',
  warn: '提示',
  block: '阻断',
}

/*
 * 状态徽章用 el-tag 的语义档，不再自绘色块。
 * 旧写法把「阻断」染成 --seal（品牌色）、「通过」染成 --lake（跌绿）、
 * 「提示」写死 #c8a400，还得配 color:#fff —— 深色档下白字块会糊成一片。
 * EP 的 danger/warning/success 已由令牌层挂到 --stamp/--warn/--success 上。
 */
type BadgeType = 'danger' | 'warning' | 'success' | 'primary' | 'info'

const statusTagType: Record<HealthCheckRow['status'], BadgeType> = {
  pending: 'info',
  running: 'primary',
  ok: 'success',
  warn: 'warning',
  block: 'danger',
}

const hasPending = computed(() => props.pendingRows.length > 0)

/**
 * idle 待检目录：按 group 归并（首次出现的顺序即展示顺序），避免 chip 云无层次。
 * 必须按名字归并而非只合并相邻项——目录里同名分组是散落的，
 * 只合并相邻会让「时效」「覆盖」这类标题重复出现好几次。
 */
const pendingGroups = computed(() => {
  const byName = new Map<string, HealthCheckRow[]>()
  for (const row of props.pendingRows) {
    const bucket = byName.get(row.group)
    if (bucket) bucket.push(row)
    else byName.set(row.group, [row])
  }
  return [...byName].map(([name, rows]) => ({ name, rows }))
})

/** 阻断优先，再提示；同级内保持原序 */
const issueGroups = computed(() => {
  const block = props.issueRows.filter((r) => r.status === 'block')
  const warn = props.issueRows.filter((r) => r.status === 'warn')
  const other = props.issueRows.filter((r) => r.status !== 'block' && r.status !== 'warn')
  const groups: { key: string; title: string | null; rows: HealthCheckRow[] }[] = []
  if (block.length) groups.push({ key: 'block', title: `阻断（${block.length}）`, rows: block })
  if (warn.length) groups.push({ key: 'warn', title: `提示（${warn.length}）`, rows: warn })
  if (other.length) groups.push({ key: 'other', title: null, rows: other })
  return groups
})

const repairableIds = computed(() =>
  props.issueRows.filter((r) => r.autoFixable).map((r) => r.id),
)

const selected = computed({
  get: () => props.selectedIds ?? [],
  set: (ids: string[]) => emit('update:selectedIds', ids),
})

const allSelected = computed(
  () =>
    repairableIds.value.length > 0 &&
    repairableIds.value.every((id) => selected.value.includes(id)),
)

const someSelected = computed(
  () =>
    repairableIds.value.some((id) => selected.value.includes(id)) && !allSelected.value,
)

watch(
  repairableIds,
  (ids) => {
    if (props.showActions) emit('update:selectedIds', [...ids])
  },
  { immediate: true },
)

function toggleAll(checked: boolean | string | number): void {
  emit('update:selectedIds', checked ? [...repairableIds.value] : [])
}

function toggleRow(rowId: string, checked: boolean | string | number): void {
  const on = Boolean(checked)
  const next = on
    ? [...new Set([...selected.value, rowId])]
    : selected.value.filter((id) => id !== rowId)
  emit('update:selectedIds', next)
}

function goManual(row: HealthCheckRow): void {
  if (row.manualRoute) void router.push(row.manualRoute)
}
</script>

<template>
  <div class="check-list">
    <template v-if="hasPending">
      <template v-if="pendingTitle === '待检'">
        <!-- 标题与提示压成一行：两行只说了「待检 N 项，点扫描」一件事 -->
        <h3 class="check-list__title">
          待检 · {{ pendingRows.length }} 项
          <span class="check-list__hint">点「一键扫描」开始核对</span>
        </h3>
        <div class="check-list__catalog" aria-label="检查目录">
          <template v-for="group in pendingGroups" :key="group.name">
            <p class="check-list__sub">{{ group.name }}（{{ group.rows.length }}）</p>
            <div
              v-for="row in group.rows"
              :key="`c-${row.id}`"
              class="check-row check-row--pending check-row--compact"
            >
              <div class="check-row__body">
                <p class="check-row__label">{{ row.label }}</p>
              </div>
              <el-tag class="check-row__badge" size="small" effect="plain" :type="statusTagType[row.status]">
                {{ statusLabel[row.status] }}
              </el-tag>
            </div>
          </template>
        </div>
      </template>
      <template v-else>
        <h3 class="check-list__title">{{ pendingTitle || '扫描中' }}</h3>
        <div
          v-for="row in pendingRows"
          :key="`p-${row.id}`"
          class="check-row"
          :class="`check-row--${row.status}`"
        >
          <span class="check-row__group">{{ row.group }}</span>
          <div class="check-row__body">
            <p class="check-row__label">{{ row.label }}</p>
            <p v-if="row.message" class="check-row__msg">{{ row.message }}</p>
          </div>
          <el-tag class="check-row__badge" size="small" effect="plain" :type="statusTagType[row.status]">
            {{ statusLabel[row.status] }}
          </el-tag>
        </div>
      </template>
    </template>

    <template v-if="issueRows.length">
      <div class="check-list__head">
        <h3 class="check-list__title">待处理</h3>
        <el-checkbox
          v-if="showActions && repairableIds.length"
          :model-value="allSelected"
          :indeterminate="someSelected"
          @change="toggleAll"
        >
          全选可修
        </el-checkbox>
      </div>

      <template v-for="group in issueGroups" :key="group.key">
        <p v-if="group.title" class="check-list__sub">{{ group.title }}</p>
        <div
          v-for="row in group.rows"
          :key="`i-${row.id}`"
          class="check-row"
          :class="[`check-row--${row.status}`, { 'check-row--selectable': showActions && row.autoFixable }]"
        >
          <el-checkbox
            v-if="showActions && row.autoFixable"
            :model-value="selected.includes(row.id)"
            :disabled="!!repairBusy"
            @change="(v: boolean | string | number) => toggleRow(row.id, v)"
          />
          <span v-else class="check-row__group">{{ row.group }}</span>
          <div class="check-row__body">
            <p class="check-row__label">
              <span v-if="showActions && row.autoFixable" class="check-row__group-inline">{{
                row.group
              }}</span>
              {{ row.label }}
            </p>
            <p v-if="row.message" class="check-row__msg">{{ row.message }}</p>
            <p v-if="row.hint" class="check-row__hint">{{ row.hint }}</p>
            <el-button
              v-if="showActions && row.autoFixable"
              size="small"
              type="primary"
              plain
              :loading="repairBusy === row.id"
              :disabled="!!repairBusy"
              @click="emit('repair', row)"
            >
              {{ row.remediation?.label || '修复' }}
            </el-button>
            <el-button
              v-else-if="showActions && row.remediation && !row.autoFixable"
              size="small"
              plain
              @click="goManual(row)"
            >
              {{ row.remediation.label || '去处理' }}
            </el-button>
          </div>
          <el-tag class="check-row__badge" size="small" effect="plain" :type="statusTagType[row.status]">
            {{ statusLabel[row.status] }}
          </el-tag>
        </div>
      </template>
    </template>

    <template v-if="okRows.length && !hasPending">
      <el-button type="primary" link class="check-list__fold" @click="okOpen = !okOpen">
        已通过（{{ okRows.length }}）
        <span class="dim">{{ okOpen ? '收起' : '展开' }}</span>
      </el-button>
      <template v-if="okOpen">
        <div
          v-for="row in okRows"
          :key="`o-${row.id}`"
          class="check-row check-row--ok"
        >
          <span class="check-row__group">{{ row.group }}</span>
          <div class="check-row__body">
            <p class="check-row__label">{{ row.label }}</p>
            <p v-if="row.message" class="check-row__msg">{{ row.message }}</p>
          </div>
          <el-tag class="check-row__badge" size="small" effect="plain" type="success">通过</el-tag>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.check-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  margin-top: var(--gap-1);
}
.check-list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  margin-top: var(--gap-1);
}
.check-list__title {
  margin: var(--gap-1) 0 2px;
  font-size: var(--fs-aux);
  font-weight: 700;
  color: var(--mist);
  letter-spacing: 0.04em;
}
.check-list__sub {
  margin: var(--gap-1) 0 0;
  font-size: var(--fs-kicker);
  font-weight: 700;
  color: var(--mist);
  letter-spacing: 0.03em;
}
/* 提示与标题同行：小一号、常规字重，只做尾注 */
.check-list__hint {
  margin-left: var(--gap-2);
  font-size: var(--fs-kicker);
  font-weight: 400;
  letter-spacing: 0;
  color: var(--mist);
}
.check-list__catalog {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
}
.check-list__catalog .check-list__sub {
  margin: var(--gap-1) 0 0;
}
.check-list__catalog .check-list__sub:first-child {
  margin-top: 0;
}
.check-list__fold {
  margin: var(--gap-2) 0 0;
  padding: 0 !important;
  height: auto !important;
  font-size: var(--fs-aux);
  font-weight: 700;
  color: var(--mist) !important;
  justify-content: flex-start;
}
.check-list__fold:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: 2px;
}
/* D3：1px hairline + 3px 圆角，无阴影；行高由内容驱动 */
.check-row {
  display: grid;
  grid-template-columns: 3.2rem minmax(0, 1fr) auto;
  gap: var(--gap-2);
  align-items: start;
  padding: var(--gap-1) var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  font-size: var(--fs-body);
  line-height: 1.45;
}
.check-row--selectable {
  grid-template-columns: auto minmax(0, 1fr) auto;
}
.check-row--compact {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  min-height: var(--row-h);
  padding: 0 var(--gap-2);
}
/* 阻断 / 提示的边框走状态色（--stamp / --warn），不借品牌色也不借涨跌色 */
.check-row--block {
  border-color: color-mix(in srgb, var(--stamp) 32%, var(--rule));
  background: color-mix(in srgb, var(--stamp) 5%, var(--sheet));
}
.check-row--warn {
  border-color: color-mix(in srgb, var(--warn) 32%, var(--rule));
}
.check-row--running {
  border-color: color-mix(in srgb, var(--seal) 24%, var(--rule));
}
.check-row__group {
  font-size: var(--fs-kicker);
  color: var(--mist);
  padding-top: 2px;
}
.check-row__group-inline {
  display: inline-block;
  margin-right: var(--gap-1);
  font-size: var(--fs-kicker);
  font-weight: 500;
  color: var(--mist);
}
.check-row__body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--gap-1);
  min-width: 0;
}
.check-row__label {
  margin: 0;
  font-weight: 600;
}
.check-row__msg,
.check-row__hint {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
}
.check-row__badge {
  flex-shrink: 0;
  align-self: start;
}
.dim {
  font-weight: 500;
  margin-left: var(--gap-1);
  opacity: 0.75;
}
</style>
