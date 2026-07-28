<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { BoardRow } from '@/shared/types/quant'

import { chgClass, fmtAmount, fmtChange, fmtPct, fmtPrice } from '../composables/dataQueryFormat'

defineProps<{
  marketQ: string
  liveOn: boolean
  liveEnriching?: boolean
  busy: boolean
  boardRows: BoardRow[]
  boardTotal: number
  page: number
  pageSize: number
}>()

const emit = defineEmits<{
  'update:marketQ': [string]
  'update:liveOn': [boolean]
  'update:page': [number]
  'update:pageSize': [number]
  search: []
  refresh: []
  pageSizeChange: []
  rowClick: [row: BoardRow]
}>()
</script>

<template>
  <section class="lookup">
    <label class="lookup__label" for="desk-q">筛选</label>
    <div class="lookup__row">
      <input
        id="desk-q"
        :value="marketQ"
        class="lookup__input"
        type="search"
        autocomplete="off"
        spellcheck="false"
        placeholder="代码 / 名称，回车筛选"
        @input="emit('update:marketQ', ($event.target as HTMLInputElement).value)"
        @keydown.enter.prevent="emit('search')"
      />
          <el-checkbox
            :model-value="liveOn"
            @update:model-value="emit('update:liveOn', Boolean($event))"
          >
            实时
          </el-checkbox>
          <span v-if="liveEnriching" class="lookup__live">刷新中…</span>
      <el-button :loading="busy" @click="emit('refresh')">刷新</el-button>
      <el-button type="primary" :loading="busy" @click="emit('search')">查询</el-button>
    </div>
    <p class="lookup__hint">
      列表默认读本机日线（分页）；勾选「实时」后，交易时段（约 09:15–15:05）在后台叠价并写入当日 K。点一行看图。
    </p>
  </section>

  <Sheet title="行情列表" :chip="boardTotal">
    <el-table
      :data="boardRows"
      size="small"
      stripe
      class="board-table"
      empty-text="无证券"
      highlight-current-row
      @row-click="emit('rowClick', $event)"
    >
      <el-table-column label="代码" width="88">
        <template #default="{ row }">
          <span class="mono board-code">{{ row.code }}</span>
        </template>
      </el-table-column>
      <el-table-column label="名称" min-width="108" prop="name" show-overflow-tooltip />
      <el-table-column label="最新" align="right" width="92">
        <template #default="{ row }">
          <span class="mono" :class="chgClass(row.pct)">{{ fmtPrice(row.price) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="涨跌%" align="right" width="88">
        <template #default="{ row }">
          <span class="mono" :class="chgClass(row.pct)">{{ fmtPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="涨跌" align="right" width="80">
        <template #default="{ row }">
          <span class="mono" :class="chgClass(row.pct)">{{ fmtChange(row.change) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="今开" align="right" width="84">
        <template #default="{ row }">{{ fmtPrice(row.open) }}</template>
      </el-table-column>
      <el-table-column label="最高" align="right" width="84">
        <template #default="{ row }">{{ fmtPrice(row.high) }}</template>
      </el-table-column>
      <el-table-column label="最低" align="right" width="84">
        <template #default="{ row }">{{ fmtPrice(row.low) }}</template>
      </el-table-column>
      <el-table-column label="成交额" align="right" min-width="100">
        <template #default="{ row }">{{ fmtAmount(row.amount) }}</template>
      </el-table-column>
      <el-table-column label="来源" width="72">
        <template #default="{ row }">
          <span class="src" :class="{ 'src--live': row.ok }">{{ row.ok ? '实时' : '日线' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="本地日" width="108">
        <template #default="{ row }">
          <span class="mono dim">{{ row.local_date || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        :total="boardTotal"
        :page-sizes="[30, 50, 100]"
        layout="total, sizes, prev, pager, next"
        background
        small
        @update:current-page="emit('update:page', $event); emit('refresh')"
        @update:page-size="emit('update:pageSize', $event); emit('pageSizeChange')"
      />
    </div>
  </Sheet>
</template>

<style scoped>
.lookup {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.lookup__label {
  font-size: 0.78rem;
  color: var(--mist);
}
.lookup__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem;
}
.lookup__input {
  flex: 1 1 220px;
  min-width: 160px;
  max-width: 360px;
  padding: 0.45rem 0.7rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  color: var(--ink);
}
.lookup__hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--mist);
}
.lookup__live {
  font-size: 0.75rem;
  color: var(--lake);
}
.board-table {
  cursor: pointer;
}
.board-code {
  font-weight: 600;
}
.src {
  font-size: 0.72rem;
  color: var(--mist);
}
.src--live {
  color: var(--lake);
}
.dim {
  color: var(--mist);
  font-size: 0.78rem;
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: 0.75rem 0.25rem 0.15rem;
}
.mono {
  font-family: var(--mono);
}
.is-up {
  color: var(--up);
}
.is-down {
  color: var(--down);
}
</style>
