<script setup lang="ts">
/**
 * 战法风格记忆卡：风格正文 / 该看哪些 / 记忆图探索 / 教训两栏。
 *
 * 与纸面舱卡同吃一个 usePaperCabin 实例——风格与记忆图本来就在 paper-cabin
 * 那一份响应里，保存风格或重建记忆图之后要重读的也是它。
 */
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
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <el-tooltip placement="top-start" content="记的是：评头论足 / 该怎么买 / 该看哪些 / 教训">
        <span>战法风格记忆 · rev {{ styleRevision }}</span>
      </el-tooltip>
    </template>
    <el-form label-position="right" label-width="6.5em" size="small" @submit.prevent>
      <el-form-item label="风格正文">
        <el-input v-model="styleMd" type="textarea" :rows="10" />
      </el-form-item>
      <el-form-item label="该看哪些">
        <el-input
          v-model="watchHintsText"
          type="textarea"
          :rows="3"
          placeholder="每行一条观察点"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="saveStyle">保存风格</el-button>
        <el-button @click="absorbStyle">吸入未消化教训</el-button>
        <el-button @click="rebuildMemory">重建记忆图</el-button>
      </el-form-item>
    </el-form>
    <el-form inline label-position="left" label-width="6.5em" class="mt" @submit.prevent>
      <el-form-item label="探索词">
        <el-input v-model="memoryQuery" style="width: 14rem" placeholder="如：高开 教训" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" plain @click="exploreMemory">探索子图</el-button>
        <span class="muted ml">{{ memoryStats }}</span>
      </el-form-item>
    </el-form>
    <!-- 记忆图摘要是内容不是异常：从 el-alert(success)+description 降成正文块 -->
    <pre v-if="memorySummary" class="plan-body__text mt">{{ memorySummary }}</pre>
    <el-table :data="memoryNodes" size="small" class="mt" max-height="200" empty-text="还没有记忆节点，先点「重建记忆图」">
      <el-table-column prop="kind" label="类型" width="90" />
      <el-table-column prop="title" label="标题" min-width="120" show-overflow-tooltip />
      <el-table-column prop="body" label="内容" min-width="160" show-overflow-tooltip />
      <el-table-column prop="weight" label="权重" width="70" />
    </el-table>
    <el-tooltip placement="top-start" content="边类型：has_rule / watches / learned_from / absorbed_into / about…">
      <span class="muted">边 {{ memoryEdges.length }} 条</span>
    </el-tooltip>
    <template v-if="roleAlertLessons.length">
      <p class="section dim">角色告警教训</p>
      <el-table
        :data="roleAlertLessons"
        size="small"
        class="role-alert-table"
        empty-text="还没有角色告警，盯盘跑过才会累积"
        max-height="200"
      >
        <el-table-column prop="trade_date" label="日期" width="110" />
        <el-table-column label="类型" width="100">
          <template #default>
            <el-tag size="small" type="warning" effect="plain">角色告警</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
        <el-table-column prop="content" label="内容" min-width="200" show-overflow-tooltip />
        <el-table-column label="已吸" width="70">
          <template #default="{ row }">{{ row.absorbed ? '是' : '否' }}</template>
        </el-table-column>
      </el-table>
    </template>
    <p v-if="regularLessons.length || !roleAlertLessons.length" class="section dim">
      {{ roleAlertLessons.length ? '其他教训' : '教训列表' }}
    </p>
    <el-table
      :data="regularLessons"
      size="small"
      empty-text="还没吸入教训，点上面「吸入未消化教训」取一批"
      max-height="240"
    >
      <el-table-column prop="trade_date" label="日期" width="110" />
      <el-table-column prop="kind" label="类型" width="90" />
      <el-table-column prop="title" label="标题" min-width="120" show-overflow-tooltip />
      <el-table-column prop="content" label="内容" min-width="180" show-overflow-tooltip />
      <el-table-column label="已吸" width="70">
        <template #default="{ row }">{{ row.absorbed ? '是' : '否' }}</template>
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
.plan-body__text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.45;
  font-family: inherit;
  font-size: var(--fs-aux);
  color: var(--el-text-color-regular);
}
.section {
  margin: var(--gap-2) 0 var(--gap-1);
  font-size: var(--fs-aux);
  color: var(--el-text-color-secondary);
}
.role-alert-table :deep(.el-table__row) {
  background: var(--el-color-warning-light-9);
}
</style>
