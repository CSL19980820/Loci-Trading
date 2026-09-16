<script setup lang="ts">
import { computed } from 'vue'
import { Plus } from '@element-plus/icons-vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import type { ApiKeyItem } from '@/shared/types/auth'

const props = defineProps<{
  apiKeys: ApiKeyItem[]
  loading?: boolean
}>()

const emit = defineEmits<{
  create: []
  revoke: [item: ApiKeyItem]
}>()

const tableRows = computed(() => props.apiKeys as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'name', label: '名称', minWidth: 140 },
  { prop: 'prefix', label: '前缀', width: 140, slotName: 'prefix' },
  { prop: 'scopes', label: '权限', width: 120, slotName: 'scopes' },
  { prop: 'created_at', label: '创建时间', minWidth: 160 },
  { prop: 'last_used_at', label: '最后使用', minWidth: 160, slotName: 'lastUsed' },
  { prop: 'revoked_at', label: '状态', width: 100, slotName: 'status' },
  { prop: 'id', label: '操作', width: 100, slotName: 'actions' },
]
</script>

<template>
  <div class="api-keys-pane flex min-h-0 flex-1 flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="text-title text-ink m-0 font-semibold">API 密钥</h3>
      <el-tag size="small" type="info" effect="plain" round>{{ apiKeys.length }}</el-tag>
      <el-tooltip content="供 OpenAPI 与自动化脚本调用 Loci 的访问凭据；明文只在创建时展示一次" placement="top">
        <el-button type="primary" class="ml-auto" :icon="Plus" @click="emit('create')">
          新建 API Key
        </el-button>
      </el-tooltip>
    </div>

    <BasicTable
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      :loading="loading"
      row-key="id"
      stripe
      empty-text="还没有 API Key"
      empty-reason="新建密钥后可连接自动化脚本"
    >
      <template #prefix="{ row }">
        <code class="font-mono">{{ row.prefix }}...</code>
      </template>
      <template #scopes="{ row }">
        <el-tag size="small" effect="plain">{{ row.scopes }}</el-tag>
      </template>
      <template #lastUsed="{ row }">
        {{ row.last_used_at || '从未使用' }}
      </template>
      <template #status="{ row }">
        <el-tag v-if="row.revoked_at" size="small" type="info" effect="plain">已撤销</el-tag>
        <el-tag v-else size="small" type="success" effect="plain">有效</el-tag>
      </template>
      <template #actions="{ row }">
        <el-button
          v-if="!row.revoked_at"
          type="danger"
          text
          size="small"
          @click="emit('revoke', row as unknown as ApiKeyItem)"
        >
          撤销
        </el-button>
      </template>
    </BasicTable>
  </div>
</template>

<style scoped>
.api-keys-pane { padding: var(--gap-3); border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface); }
</style>
