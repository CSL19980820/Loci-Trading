<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'
import { toneClass } from '@/shared/lib/format'
import type { CompareResult, OptimizeResult, StrategyInfo } from '@/shared/types/quant'

import { exitDist, signed } from '../composables/quantFormat'

defineProps<{
  strategies: StrategyInfo[]
  analysisBusy: boolean
  analysisLabel: string
  optimizeTarget: string
  analysisStart: string
  compareResult: CompareResult | null
  optimizeResult: OptimizeResult | null
  optimizeExpanded: boolean
  optimizeRowsShown: OptimizeResult['rows']
}>()

const emit = defineEmits<{
  'update:optimizeTarget': [string]
  'update:analysisStart': [string]
  'update:optimizeExpanded': [boolean]
  runCompare: []
  runOptimize: []
  clearAnalysisResults: []
}>()
</script>

<template>
  <Sheet title="分析">
    <template #actions>
      <span v-if="analysisBusy" class="muted mono">{{ analysisLabel }} 运行中…</span>
      <el-button
        v-if="compareResult || optimizeResult"
        size="small"
        text
        :disabled="analysisBusy"
        @click="emit('clearAnalysisResults')"
      >清除分析结果</el-button>
    </template>
    <div class="analysis-actions">
      <el-button :disabled="analysisBusy" @click="emit('runCompare')">横向对比全部战法</el-button>
      <el-select
        :model-value="optimizeTarget"
        :disabled="analysisBusy"
        clearable
        placeholder="选一个战法扫描退出规则"
        style="width: 14rem"
        @update:model-value="emit('update:optimizeTarget', $event ?? '')"
      >
        <el-option v-for="item in strategies" :key="item.slug" :label="item.name" :value="item.slug" />
      </el-select>
      <el-button :disabled="analysisBusy || !optimizeTarget" @click="emit('runOptimize')">扫描退出规则</el-button>
      <el-date-picker
        :model-value="analysisStart"
        type="date"
        value-format="YYYY-MM-DD"
        :disabled="analysisBusy"
        placeholder="起始"
        @update:model-value="emit('update:analysisStart', String($event ?? ''))"
      />
    </div>
    <el-collapse>
      <el-collapse-item title="口径" name="note">
        <p class="form-hint">
          对比按超额排序。「回吐」= MFE 均值 − 净收益均值。全市场跑一轮通常要几十秒到几分钟。
        </p>
      </el-collapse-item>
    </el-collapse>

    <el-table v-if="compareResult" :data="compareResult.rows" size="small" class="mb">
      <el-table-column label="战法" min-width="120">
        <template #default="{ row }"><strong>{{ row.label }}</strong></template>
      </el-table-column>
      <el-table-column label="笔数" align="right" width="80">
        <template #default="{ row }">{{ row.trades.toLocaleString('zh-CN') }}</template>
      </el-table-column>
      <el-table-column label="胜率" align="right" width="80">
        <template #default="{ row }">{{ row.win_rate.toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column label="净收益" align="right" width="90">
        <template #default="{ row }">
          <span :class="toneClass(row.avg_net_return)">{{ signed(row.avg_net_return) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="MFE" align="right" width="80">
        <template #default="{ row }"><span class="tone-up">{{ signed(row.avg_mfe ?? undefined) }}</span></template>
      </el-table-column>
      <el-table-column label="MAE" align="right" width="80">
        <template #default="{ row }"><span class="tone-down">{{ signed(row.avg_mae ?? undefined) }}</span></template>
      </el-table-column>
      <el-table-column label="超额" align="right" width="90">
        <template #default="{ row }">
          <strong :class="toneClass(row.avg_alpha ?? 0)">{{ signed(row.avg_alpha ?? undefined) }}</strong>
        </template>
      </el-table-column>
      <el-table-column label="回吐" align="right" width="90">
        <template #default="{ row }">
          {{ row.give_back.toFixed(2) }}%<span v-if="row.give_back > 4" class="tone-down"> ⚠</span>
        </template>
      </el-table-column>
    </el-table>
    <p v-if="compareResult?.hint" class="form-hint highlight-hint">{{ compareResult.hint }}</p>

    <template v-if="optimizeResult">
      <p v-if="(optimizeResult.rows?.length ?? 0) > 12" class="form-hint">
        {{ optimizeExpanded ? `全部 ${optimizeResult.rows.length} 组` : `仅展示前 12 组，共 ${optimizeResult.rows.length} 组` }}
        <el-button
          text
          type="primary"
          size="small"
          @click="emit('update:optimizeExpanded', !optimizeExpanded)"
        >
          {{ optimizeExpanded ? '收起' : '展开全部' }}
        </el-button>
      </p>
      <el-table :data="optimizeRowsShown" size="small">
        <el-table-column label="持有" align="right" width="70">
          <template #default="{ row }">{{ row.hold_days }}d</template>
        </el-table-column>
        <el-table-column label="止盈" align="right" width="80">
          <template #default="{ row }">{{ row.take_profit_pct ? signed(row.take_profit_pct) : '—' }}</template>
        </el-table-column>
        <el-table-column label="止损" align="right" width="80">
          <template #default="{ row }">{{ row.stop_loss_pct ? signed(row.stop_loss_pct) : '—' }}</template>
        </el-table-column>
        <el-table-column label="笔数" align="right" width="70" prop="trades" />
        <el-table-column label="胜率" align="right" width="80">
          <template #default="{ row }">{{ row.win_rate.toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="净收益" align="right" width="90">
          <template #default="{ row }">
            <span :class="toneClass(row.avg_net_return)">{{ signed(row.avg_net_return) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="超额" align="right" width="90">
          <template #default="{ row }">
            <strong :class="toneClass(row.avg_alpha ?? 0)">{{ signed(row.avg_alpha ?? undefined) }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="退出分布" min-width="140">
          <template #default="{ row }"><span class="dim mono">{{ exitDist(row.exit_reasons) }}</span></template>
        </el-table-column>
      </el-table>
      <p v-if="optimizeResult.best" class="form-hint highlight-hint">
        最优：持有 {{ optimizeResult.best.hold_days }} 日
        {{ optimizeResult.best.take_profit_pct ? `，止盈 ${signed(optimizeResult.best.take_profit_pct)}` : '，不设止盈' }}
        {{ optimizeResult.best.stop_loss_pct ? `，止损 ${signed(optimizeResult.best.stop_loss_pct)}` : '，不设止损' }}
        <span v-if="optimizeResult.improvement !== null">
          （比只按持有期了结高 {{ signed(optimizeResult.improvement) }}）
        </span>
      </p>
      <p class="form-error">{{ optimizeResult.warning }}</p>
    </template>
  </Sheet>
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}
.dim {
  color: var(--mist);
  font-size: 0.82rem;
}
</style>
