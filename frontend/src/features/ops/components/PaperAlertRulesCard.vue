<script setup lang="ts">
/**
 * 价格提醒卡：填代码与价位加一条规则，或试扫一遍看命中几条。
 *
 * 规则与当前战法 slug 无关，所以这张卡自带 useAlertRules，自己拉自己的列表。
 */
import { onMounted } from 'vue'

import { useAlertRules } from '../composables/useAlertRules'

const { alertCode, alertPrice, rules, loadRules, addRule, scanRules } = useAlertRules()

onMounted(() => {
  void loadRules()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>价格提醒规则</template>
    <el-form inline label-position="left" label-width="6.5em" @submit.prevent>
      <el-form-item label="代码">
        <el-input v-model="alertCode" style="width: 8rem" />
      </el-form-item>
      <el-form-item label="价≥">
        <el-input-number v-model="alertPrice" :step="0.01" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="addRule">添加</el-button>
        <el-button @click="scanRules">试扫</el-button>
      </el-form-item>
    </el-form>
    <el-table :data="rules" size="small" empty-text="还没有规则，填好代码与价格后点「添加」">
      <el-table-column prop="code" label="代码" width="100" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="enabled" label="启用" width="70" />
    </el-table>
  </el-card>
</template>
