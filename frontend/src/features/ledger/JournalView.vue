<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import ImportStateDialog from '@/shared/components/dialogs/ImportStateDialog.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import TableFoot from '@/shared/components/ui/TableFoot.vue'
import TradeDialog from '@/shared/components/dialogs/TradeDialog.vue'
import TradesTable from '@/features/ledger/components/TradesTable.vue'
import { exportTradesCsv } from '@/shared/api/palace'
import { signedMoney } from '@/shared/lib/format'
import { useClientPagination } from '@/shared/composables/useClientPagination'
import { usePalaceStore } from '@/shared/stores/palace'

const store = usePalaceStore()
const router = useRouter()
const route = useRoute()
const tradeDialogOpen = ref(false)
const importDialogOpen = ref(false)
const exporting = ref(false)

const { currentPage, pageSize, paginated } = useClientPagination(() => store.trades, 20)

const buyCount = computed(() => store.trades.filter((item) => item.action === 'BUY' || item.action === 'OPENING').length)
const sellCount = computed(() => store.trades.filter((item) => item.action === 'SELL').length)
const sellPnl = computed(() =>
  store.trades.filter((item) => item.action === 'SELL').reduce((sum, item) => sum + item.realized_pnl, 0),
)

function goArchive(code: string): void {
  void router.push(`/archive/${code}`)
}

async function onExportCsv(): Promise<void> {
  exporting.value = true
  try {
    await exportTradesCsv()
    ElMessage.success('交割单已导出')
  } catch (caught: unknown) {
    ElMessage.error(caught instanceof Error ? caught.message : '导出失败')
  } finally {
    exporting.value = false
  }
}

async function onImportSaved(): Promise<void> {
  await store.loadRoute(route, true)
}
</script>

<template>
  <PageHeader title="交割单" :subtitle="`买 ${buyCount} · 卖 ${sellCount} · ${signedMoney(sellPnl)}`">
    <el-tag size="small" type="info">{{ store.trades.length }} 笔</el-tag>
    <el-button text @click="importDialogOpen = true">导入</el-button>
    <el-button text :loading="exporting" @click="onExportCsv">导出</el-button>
    <el-button @click="tradeDialogOpen = true">写入成交</el-button>
  </PageHeader>

  <Sheet>
    <TradesTable
      v-if="store.trades.length"
      :trades="paginated"
      show-stock
      row-clickable
      @row-click="(row) => goArchive(row.code)"
    />
    <EmptyState
      v-else
      description="还没有成交"
      reason="还没记过成交或未导入潜龙 state"
      eta="记一笔或导入后立即出现"
    >
      <el-button type="primary" @click="tradeDialogOpen = true">写入成交</el-button>
      <el-button @click="importDialogOpen = true">导入 state</el-button>
    </EmptyState>
    <TableFoot v-model:page="currentPage" :total="store.trades.length" :page-size="pageSize" />
  </Sheet>

  <TradeDialog v-model="tradeDialogOpen" />
  <ImportStateDialog v-model="importDialogOpen" @saved="onImportSaved" />
</template>

<style scoped>
:deep(.el-table__row) {
  cursor: pointer;
}
</style>
