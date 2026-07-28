<script setup lang="ts">
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import RowActions from '@/shared/components/ui/RowActions.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { StrategyInfo } from '@/shared/types/quant'

defineProps<{
  strategies: StrategyInfo[]
}>()

const emit = defineEmits<{
  screen: [slug: string]
  backtest: [slug: string]
  config: [slug: string]
}>()
</script>

<template>
  <Sheet title="战法" :chip="strategies.length">
    <el-table v-if="strategies.length" :data="strategies" size="small">
      <el-table-column label="战法" min-width="140">
        <template #default="{ row }">
          <strong>{{ row.name }}</strong>
        </template>
      </el-table-column>
      <el-table-column label="入场" width="110">
        <template #default="{ row }">
          <span class="tag">{{ row.entry_timing === 'open' ? '当日开盘' : '次日开盘' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最少K线" align="right" width="100" prop="min_bars" />
      <el-table-column label="说明" min-width="180" show-overflow-tooltip prop="description" />
      <el-table-column label="操作" align="right" width="168" fixed="right">
        <template #default="{ row }">
          <RowActions
            :actions="[
              { key: 'screen', label: '跑选股', onClick: () => emit('screen', row.slug) },
              { key: 'backtest', label: '回测', onClick: () => emit('backtest', row.slug) },
              { key: 'config', label: '配置', onClick: () => emit('config', row.slug) },
            ]"
          />
        </template>
      </el-table-column>
    </el-table>
    <EmptyState v-else description="无已注册战法" />
    <el-collapse>
      <el-collapse-item title="口径" name="note">
        <p class="form-hint">
          入场时点是战法属性：用到当日收盘/最高/最低的战法只能次日开盘入场。
        </p>
      </el-collapse-item>
    </el-collapse>
  </Sheet>
</template>
