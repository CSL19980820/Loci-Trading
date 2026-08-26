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
        <h3 class="check-list__title">待检 · {{ pendingRows.length }} 项</h3>
        <p class="check-list__idle-hint">点上方「一键扫描」开始核对；深度扫描会额外探数据源连通。</p>
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
              <span class="check-row__badge">{{ statusLabel[row.status] }}</span>
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
          <span class="check-row__badge">{{ statusLabel[row.status] }}</span>
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
          <span class="check-row__badge">{{ statusLabel[row.status] }}</span>
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
          <span class="check-row__badge">通过</span>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.check-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-top: 0.35rem;
}

.check-list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  margin-top: 0.35rem;
}

.check-list__title {
  margin: 0.2rem 0 0.25rem;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--mist);
  letter-spacing: 0.04em;
}

.check-list__sub {
  margin: 0.35rem 0 0.1rem;
  font-size: 0.72rem;
  font-weight: 650;
  color: var(--mist);
  letter-spacing: 0.03em;
}

.check-list__idle-hint {
  margin: 0 0 0.35rem;
  font-size: 0.78rem;
  color: var(--mist);
  line-height: 1.4;
}

.check-list__catalog {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.check-list__catalog .check-list__sub {
  margin: 0.4rem 0 0.05rem;
}

.check-list__catalog .check-list__sub:first-child {
  margin-top: 0;
}

.check-list__fold {
  margin: 0.55rem 0 0.15rem;
  padding: 0 !important;
  height: auto !important;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--mist) !important;
  justify-content: flex-start;
}

.check-list__fold:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: 2px;
}

.check-row {
  display: grid;
  grid-template-columns: 3.2rem 1fr auto;
  gap: 0.55rem;
  align-items: start;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--sheet) 88%, #fff);
  font-size: 0.86rem;
  line-height: 1.45;
}

.check-row--selectable {
  grid-template-columns: auto 1fr auto;
}

.check-row--compact {
  grid-template-columns: 1fr auto;
  align-items: center;
  padding: 0.35rem 0.65rem;
}

.check-row--block {
  border-color: color-mix(in srgb, var(--seal) 28%, var(--rule));
  background: color-mix(in srgb, var(--seal-soft) 40%, var(--sheet));
}

.check-row--warn {
  border-color: color-mix(in srgb, #c8a400 30%, var(--rule));
}

.check-row--running {
  border-color: color-mix(in srgb, var(--seal) 22%, var(--rule));
}

.check-row__group {
  font-size: 0.72rem;
  color: var(--mist);
  padding-top: 0.12rem;
}

.check-row__group-inline {
  display: inline-block;
  margin-right: 0.4rem;
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--mist);
}

.check-row__body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.28rem;
  min-width: 0;
}

.check-row__label {
  margin: 0;
  font-weight: 600;
}

.check-row__msg,
.check-row__hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--mist);
}

.check-row__badge {
  font-size: 0.68rem;
  padding: 0.12rem 0.4rem;
  border-radius: 3px;
  font-weight: 650;
  letter-spacing: 0.04em;
  flex-shrink: 0;
  background: var(--mist);
  color: #fff;
}

.check-row--ok .check-row__badge {
  background: var(--lake);
}

.check-row--block .check-row__badge {
  background: var(--seal);
}

.check-row--warn .check-row__badge {
  background: #c8a400;
}

.check-row--running .check-row__badge {
  background: var(--seal-ink);
}

.check-row--pending .check-row__badge {
  background: color-mix(in srgb, var(--mist) 55%, var(--rule));
}

.dim {
  font-weight: 500;
  margin-left: 0.35rem;
  opacity: 0.75;
}
</style>
