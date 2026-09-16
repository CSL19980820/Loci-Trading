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
  <div class="check-list" role="region" aria-label="数据检查项">
    <template v-if="hasPending">
      <template v-if="pendingTitle === '待检'">
        <!-- 标题与提示压成一行：两行只说了「待检 N 项，点扫描」一件事 -->
        <h3 class="check-list__title">
          待检 · {{ pendingRows.length }} 项
          <span class="check-list__hint">点「一键扫描」开始核对</span>
        </h3>
        <div class="check-list__catalog" aria-label="检查目录">
          <section v-for="group in pendingGroups" :key="group.name" class="check-group">
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
          </section>
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
            :aria-label="`选择修复：${row.label}`"
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
      <el-button type="primary" link class="check-list__fold" :aria-expanded="okOpen" @click="okOpen = !okOpen">
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

<style scoped src="./HealthCheckList.css" />
