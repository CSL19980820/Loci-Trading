<script setup lang="ts">
import { computed } from 'vue'
import { Plus } from '@element-plus/icons-vue'

import type { ApiKeyItem } from '@/shared/types/auth'

defineProps<{
  apiKeys: ApiKeyItem[]
  loading?: boolean
}>()

const emit = defineEmits<{
  create: []
  revoke: [item: ApiKeyItem]
}>()
</script>

<template>
  <div class="apikeys-tab">
    <div class="sec-header-row">
      <h3 class="sec-title">API 密钥</h3>
      <el-tag size="small" type="info" round>{{ apiKeys.length }}</el-tag>
      <el-tooltip content="供 OpenAPI 与自动化脚本调用 Loci 的访问凭据；明文只在创建时展示一次" placement="top">
        <el-button type="primary" :icon="Plus" @click="emit('create')">
          新建 API Key
        </el-button>
      </el-tooltip>
    </div>

    <div v-loading="loading" class="api-key-list">
      <el-table :data="apiKeys" empty-text="暂无 API Key" style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="140" align="center" header-align="center" />
        <el-table-column prop="prefix" label="前缀" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <code>{{ row.prefix }}...</code>
          </template>
        </el-table-column>
        <el-table-column prop="scopes" label="权限" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag size="small">{{ row.scopes }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="160" align="center" header-align="center" />
        <el-table-column prop="last_used_at" label="最后使用" min-width="160" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.last_used_at || '从未使用' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag v-if="row.revoked_at" size="small" type="danger">已撤销</el-tag>
            <el-tag v-else size="small" type="success">有效</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center" header-align="center">
          <template #default="{ row }">
            <el-button
              v-if="!row.revoked_at"
              type="danger"
              text
              size="small"
              @click="emit('revoke', row)"
            >
              撤销
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.sec-header-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.sec-header-row .el-button {
  margin-left: auto;
}

.sec-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--ink);
}
</style>
