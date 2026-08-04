<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { HealthCheckRow } from '@/features/review/composables/useHealthCheckup'

const props = defineProps<{
  issueRows: HealthCheckRow[]
  okRows: HealthCheckRow[]
  pendingRows: HealthCheckRow[]
  repairBusy: string
  showActions?: boolean
  selectedIds?: string[]
}>()

const emit = defineEmits<{
  repair: [row: HealthCheckRow]
  'update:selectedIds': [ids: string[]]
}>()

const okOpen = ref(false)

const statusLabel: Record<HealthCheckRow['status'], string> = {
  pending: '待检',
  running: '扫描',
  ok: '通过',
  warn: '提示',
  block: '阻断',
}

const hasPending = computed(() => props.pendingRows.length > 0)

const repairableIds = computed(() =>
  props.issueRows.filter((r) => r.remediation).map((r) => r.id),
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
    // 新扫描结果：默认全选可修项
    if (props.showActions) emit('update:selectedIds', [...ids])
  },
  { immediate: true },
)

function toggleAll(checked: boolean | string | number): void {
  emit('update:selectedIds', checked ? [...repairableIds.value] : [])
}
</script>

<template>
  <div class="check-list">
    <template v-if="hasPending">
      <h3 class="check-list__title">扫描中</h3>
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
      <div
        v-for="row in issueRows"
        :key="`i-${row.id}`"
        class="check-row"
        :class="[`check-row--${row.status}`, { 'check-row--selectable': showActions && row.remediation }]"
      >
        <el-checkbox
          v-if="showActions && row.remediation"
          :model-value="selected.includes(row.id)"
          :disabled="!!repairBusy"
          @change="
            (v: boolean | string | number) => {
              const on = Boolean(v)
              const next = on
                ? [...new Set([...selected, row.id])]
                : selected.filter((id) => id !== row.id)
              emit('update:selectedIds', next)
            }
          "
        />
        <span v-else class="check-row__group">{{ row.group }}</span>
        <div class="check-row__body">
          <p class="check-row__label">
            <span v-if="showActions && row.remediation" class="check-row__group-inline">{{
              row.group
            }}</span>
            {{ row.label }}
          </p>
          <p v-if="row.message" class="check-row__msg">{{ row.message }}</p>
          <p v-if="row.hint" class="check-row__hint">{{ row.hint }}</p>
          <el-button
            v-if="showActions && row.remediation"
            size="small"
            type="primary"
            plain
            :loading="repairBusy === row.id"
            :disabled="!!repairBusy"
            @click="emit('repair', row)"
          >
            {{ row.remediation.label || '修复' }}
          </el-button>
        </div>
        <span class="check-row__badge">{{ statusLabel[row.status] }}</span>
      </div>
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
