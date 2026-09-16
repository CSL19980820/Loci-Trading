<script setup lang="ts">
/**
 * 战法风格记忆卡：风格正文 / 该看哪些 / 记忆图探索 / 教训两栏。
 *
 * 与纸面舱卡同吃一个 usePaperCabin 实例——风格与记忆图本来就在 paper-cabin
 * 那一份响应里，保存风格或重建记忆图之后要重读的也是它。
 */
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'

import SettingsPanel from './SettingsPanel.vue'
import type { PaperCabinStore } from '../composables/usePaperCabin'

const props = defineProps<{ cabin: PaperCabinStore }>()

const {
  styleMd,
  styleRevision,
  watchHintsText,
  memoryQuery,
  memoryStats,
  memorySummary,
  memoryNodes,
  memoryEdges,
  roleAlertLessons,
  regularLessons,
  saveStyle,
  absorbStyle,
  exploreMemory,
  rebuildMemory,
} = props.cabin

const nodeRows = computed(() => memoryNodes.value as unknown as Record<string, unknown>[])
const roleAlertRows = computed(() => roleAlertLessons.value as unknown as Record<string, unknown>[])
const regularRows = computed(() => regularLessons.value as unknown as Record<string, unknown>[])

const nodeColumns: BasicTableColumn[] = [
  { prop: 'kind', label: '类型', width: 90 },
  { prop: 'title', label: '标题', minWidth: 120, showOverflowTooltip: true },
  { prop: 'body', label: '内容', minWidth: 160, showOverflowTooltip: true },
  { prop: 'weight', label: '权重', width: 70 },
]

const lessonColumns: BasicTableColumn[] = [
  { prop: 'trade_date', label: '日期', width: 110 },
  { prop: 'kind', label: '类型', width: 90, slotName: 'kind' },
  { prop: 'title', label: '标题', minWidth: 140, showOverflowTooltip: true },
  { prop: 'content', label: '内容', minWidth: 180, showOverflowTooltip: true },
  { prop: 'absorbed', label: '已吸', width: 70, formatter: (row) => (row.absorbed ? '是' : '否') },
]
</script>

<template>
  <SettingsPanel title="战法风格记忆" :receipt="[{ key: 'rev', value: String(styleRevision) }]">
    <template #action>
      <el-tooltip placement="top-start" content="记的是：评头论足 / 该怎么买 / 该看哪些 / 教训">
        <el-button type="primary" size="small" @click="saveStyle">保存风格</el-button>
      </el-tooltip>
      <el-button size="small" @click="absorbStyle">吸入未消化教训</el-button>
      <el-button size="small" @click="rebuildMemory">重建记忆图</el-button>
    </template>

    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <el-form-item label="风格正文">
        <el-input v-model="styleMd" type="textarea" :rows="10" />
      </el-form-item>
      <el-form-item label="该看哪些" class="mb-0">
        <el-input
          v-model="watchHintsText"
          type="textarea"
          :rows="3"
          placeholder="每行一条观察点"
        />
      </el-form-item>
    </el-form>

    <el-form
      inline
      label-position="left"
      label-width="6.5em"
      size="small"
      class="mt-2 flex flex-wrap items-center gap-x-3"
      @submit.prevent
    >
      <el-form-item label="探索词">
        <el-input v-model="memoryQuery" class="memory-query" placeholder="如：高开 教训" />
      </el-form-item>
      <el-form-item class="mb-0">
        <el-button type="primary" plain size="small" @click="exploreMemory">探索子图</el-button>
        <span class="text-aux text-mist ml-2">{{ memoryStats }}</span>
      </el-form-item>
    </el-form>

    <pre v-if="memorySummary" class="memory-summary">{{ memorySummary }}</pre>

    <BasicTable
      class="mt-2"
      :columns="nodeColumns"
      :data-source="nodeRows"
      :pagination="false"
      max-height="200"
      stripe
      empty-text="还没有记忆节点"
      empty-reason="先点「重建记忆图」"
    />

    <el-tooltip placement="top-start" content="边类型：has_rule / watches / learned_from / absorbed_into / about…">
      <span class="text-aux text-mist mt-2 inline-block">边 {{ memoryEdges.length }} 条</span>
    </el-tooltip>

    <p v-if="roleAlertLessons.length" class="text-aux text-mist mt-2 mb-1">角色告警教训</p>
    <BasicTable
      v-if="roleAlertLessons.length"
      :columns="lessonColumns"
      :data-source="roleAlertRows"
      :pagination="false"
      max-height="200"
      stripe
      :row-class-name="() => 'role-alert-row'"
      empty-text="还没有角色告警"
      empty-reason="盯盘跑过才会累积"
    >
      <template #kind>
        <el-tag size="small" type="warning" effect="plain">角色告警</el-tag>
      </template>
    </BasicTable>

    <p class="text-aux text-mist mt-2 mb-1">
      {{ roleAlertLessons.length ? '其他教训' : '教训列表' }}
    </p>
    <BasicTable
      :columns="lessonColumns"
      :data-source="regularRows"
      :pagination="false"
      max-height="240"
      stripe
      empty-text="还没吸入教训"
      empty-reason="点上面「吸入未消化教训」取一批"
    >
      <template #kind="{ row }">{{ row.kind }}</template>
    </BasicTable>
  </SettingsPanel>
</template>

<style scoped>
:deep(.role-alert-row) {
  background: var(--warn-soft);
}
.memory-query { width: min(14rem, 100%); }
.memory-summary { padding: var(--gap-3); margin: var(--gap-2) 0 0; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface-sunken); color: var(--ink); font: var(--fs-body)/1.6 var(--font); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
