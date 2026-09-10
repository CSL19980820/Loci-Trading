<script setup lang="ts">
/**
 * 纸面舱卡：舱配置表单 + 两道闸门读数 + 持仓 + 次日情景预案。
 *
 * 与风格记忆卡共读同一个 usePaperCabin 实例（同一份 paper-cabin 响应），所以
 * store 由面板建好后按 prop 传进来；这张卡只负责把结论摆上去。
 */
import { cnStrategyName } from '../composables/opsLabels'
import type { PaperCabinStore } from '../composables/usePaperCabin'

const props = defineProps<{ cabin: PaperCabinStore }>()

const {
  slug,
  followWecom,
  model,
  thinking,
  maxLayers,
  gapUpChase,
  unifiedPool,
  positions,
  fills,
  plan,
  planItems,
  latestMarketGate,
  latestMarketGateType,
  tradingDayGateAlert,
  scenarioLabel,
  loadCabin,
  saveCabin,
  monitorNow,
  eodNow,
} = props.cabin
</script>

<template>
  <el-card shadow="never">
    <template #header>纸面量化舱</template>
    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <el-form-item label="战法标识">
        <el-input v-model="slug" style="max-width: 12rem" />
        <!-- slug 是英文编码，展示位必须给中文名：走共享词表（含拼音词根兜底） -->
        <el-tag class="ml" size="small" effect="plain">{{ cnStrategyName('', slug.trim() || 'demo') }}</el-tag>
        <el-button class="ml" @click="loadCabin">刷新</el-button>
      </el-form-item>
      <el-form-item label="企微跟随">
        <el-switch v-model="followWecom" />
      </el-form-item>
      <el-form-item label="模型">
        <el-input v-model="model" placeholder="空则情景门闩（非盲目开仓）" />
      </el-form-item>
      <el-form-item label="思考档">
        <el-select v-model="thinking" style="width: 10rem">
          <el-option label="off" value="off" />
          <el-option label="low" value="low" />
          <el-option label="medium" value="medium" />
          <el-option label="high" value="high" />
        </el-select>
      </el-form-item>
      <el-form-item label="满仓层数">
        <el-input-number v-model="maxLayers" :min="1" :max="20" :step="0.5" />
      </el-form-item>
      <el-form-item label="高开可追">
        <el-tooltip placement="top-start" content="默认不追；开启后只在浅高开时买半层">
          <el-switch v-model="gapUpChase" />
        </el-tooltip>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="saveCabin">保存舱配置</el-button>
        <!-- 绿是「成功状态」不是动作色：次级动作用 plain 主色，别在同一排里撞出两种色相 -->
        <el-button type="primary" plain @click="monitorNow">立即盯盘</el-button>
        <el-button @click="eodNow">日终总结</el-button>
      </el-form-item>
    </el-form>
    <p class="muted">
      统一监察池：持股 {{ String((unifiedPool as { counts?: { positions?: number } } | null)?.counts?.positions ?? positions.length) }}/3
      · 观察 {{ String((unifiedPool as { counts?: { observe?: number } } | null)?.counts?.observe ?? 0) }}/5
      · 最近成交 {{ fills.length }} · 20万底仓 / 100%
    </p>
    <!-- 交易日闸是真异常：留 el-alert，标题 ≤20 字；备注（note）进 tooltip -->
    <el-tooltip
      v-if="tradingDayGateAlert"
      placement="top-start"
      :content="tradingDayGateAlert.note"
    >
      <el-alert
        class="mt"
        :type="tradingDayGateAlert.type"
        :closable="false"
        show-icon
        :title="tradingDayGateAlert.title"
      />
    </el-tooltip>
    <!-- 龙空龙闸门是状态读数，不报错：从 el-alert 降成一行 chip + 读数，理由进 tooltip -->
    <p v-if="latestMarketGate" class="gate-row mt">
      <el-tag size="small" effect="plain" :type="latestMarketGateType">
        龙空龙闸门 {{ String(latestMarketGate.mode || '观察') }}
      </el-tag>
      <el-tooltip placement="top-start" :content="String(latestMarketGate.reason || '这次没有给出闸门说明')">
        <span class="muted">{{ String(latestMarketGate.label || '—') }}</span>
      </el-tooltip>
    </p>
    <el-table :data="positions" size="small" empty-text="纸面舱还没有持仓，盯盘买进后会记在这里">
      <el-table-column prop="code" label="代码" width="100" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="layers" label="层" width="80" />
      <el-table-column prop="mark_cost" label="标记成本" width="100" />
    </el-table>
    <!--
      次日情景预案是**内容**，不是异常：原来塞进 el-alert 的 description 里。
      改成正文块，标题与预案日期同一行，正文按原样保留换行。
    -->
    <section v-if="plan" class="plan-body mt">
      <p class="plan-body__head">
        <strong>次日情景预案</strong>
        <span class="mono">{{ (plan as { plan_date?: string }).plan_date || '—' }}</span>
      </p>
      <pre class="plan-body__text">{{ String((plan as { body_text?: string }).body_text || '') }}</pre>
    </section>
    <el-table
      v-if="planItems.length"
      class="mt"
      :data="planItems"
      size="small"
      empty-text="这份预案只给了整体判断，没有列到个股"
    >
      <el-table-column prop="code" label="代码" width="90" />
      <el-table-column prop="name" label="名称" width="100" />
      <el-table-column prop="action" label="动作" width="80" />
      <el-table-column prop="thesis" label="想法" min-width="120" show-overflow-tooltip />
      <el-table-column label="高开" min-width="120">
        <template #default="{ row }">{{ scenarioLabel(row, 'gap_up') }}</template>
      </el-table-column>
      <el-table-column label="平开" min-width="120">
        <template #default="{ row }">{{ scenarioLabel(row, 'flat') }}</template>
      </el-table-column>
      <el-table-column label="低开" min-width="120">
        <template #default="{ row }">{{ scenarioLabel(row, 'gap_down') }}</template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.ml {
  margin-left: var(--gap-2);
}
.mt {
  margin-top: var(--gap-2);
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: var(--fs-aux);
}
/* 预案 / 记忆图摘要：正文块，保留原文换行 */
.plan-body {
  padding: var(--gap-2) 0 0;
}
.plan-body__head {
  display: flex;
  align-items: baseline;
  gap: var(--gap-2);
  margin: 0 0 var(--gap-1);
  font-size: var(--fs-aux);
}
.plan-body__text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.45;
  font-family: inherit;
  font-size: var(--fs-aux);
  color: var(--el-text-color-regular);
}
.gate-row {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin: var(--gap-2) 0 0;
}
.mono {
  font-family: var(--mono);
}
</style>
