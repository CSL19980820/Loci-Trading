<script setup lang="ts">
import { reactive, ref } from 'vue'

import {
  deleteMcpServer,
  getMcpServers,
  refreshMcpTools,
  saveMcpServer,
  toggleMcpServer,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import type { McpServer } from '@/shared/types/quant'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const { busy, notice, guard } = useOpsFeedback()

const mcpServers = ref<McpServer[]>([])
const mcpFormOpen = ref(false)
const mcpForm = reactive({
  name: '',
  url: '',
  token: '',
  proxy_url: '',
  note: '',
  verify: true,
})

async function load(): Promise<void> {
  mcpServers.value = await getMcpServers()
}

async function submitMcp(): Promise<void> {
  const saved = await guard(() =>
    saveMcpServer({
      name: mcpForm.name,
      url: mcpForm.url,
      token: mcpForm.token || undefined,
      proxy_url: mcpForm.proxy_url,
      note: mcpForm.note,
      verify: mcpForm.verify,
    }),
  )
  if (saved) {
    notice.value = `已保存 ${saved.name}，发现 ${saved.tools.length} 个工具`
    mcpFormOpen.value = false
    Object.assign(mcpForm, { name: '', url: '', token: '', proxy_url: '', note: '', verify: true })
    await load()
  }
}

async function refreshMcp(name: string): Promise<void> {
  const result = await guard(() => refreshMcpTools(name))
  if (result) {
    notice.value = `${name} 已刷新，${result.count} 个工具`
    await load()
  }
}

async function toggleMcp(item: McpServer): Promise<void> {
  await guard(() => toggleMcpServer(item.name, !item.is_active))
  await load()
}

async function confirmDropMcp(name: string): Promise<void> {
  if (!(await confirmDangerous(`确定删除 MCP Server「${name}」？`, '确认删除', '删除'))) return
  await guard(() => deleteMcpServer(name), `已删除 ${name}`)
  await load()
}

defineExpose({ load })
</script>

<template>
  <Sheet title="MCP Server" :chip="mcpServers.length">
    <template #actions>
      <el-button type="primary" link @click="mcpFormOpen = true">添加</el-button>
    </template>

    <div v-if="mcpServers.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>名称</th>
            <th>URL</th>
            <th>Token</th>
            <th class="r">工具数</th>
            <th>同步时间</th>
            <th class="r">状态</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in mcpServers" :key="item.id">
            <td>
              <strong>{{ item.name }}</strong>
              <span v-if="item.builtin" class="tag">内置</span>
              <p v-if="item.note" class="reason">{{ item.note }}</p>
            </td>
            <td class="mono dim">{{ item.url || (item.builtin ? 'in-process' : '—') }}</td>
            <td class="mono">{{ item.builtin ? '—' : item.token_last4 || '无' }}</td>
            <td class="r mono">{{ item.tools.length }}</td>
            <td class="mono dim">{{ item.tools_synced_at?.slice(0, 16) || '—' }}</td>
            <td class="r">
              <span :class="item.is_active ? 'tag' : 'chip muted-chip'">
                {{ item.is_active ? '启用' : '停用' }}
              </span>
            </td>
            <td class="r">
              <template v-if="item.builtin">
                <span class="dim">随应用启动</span>
              </template>
              <template v-else>
                <el-button size="small" text :disabled="busy" @click="refreshMcp(item.name)">
                  刷新
                </el-button>
                <el-button size="small" text :disabled="busy" @click="toggleMcp(item)">
                  {{ item.is_active ? '停用' : '启用' }}
                </el-button>
                <el-button size="small" text :disabled="busy" @click="confirmDropMcp(item.name)">
                  删除
                </el-button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      description="尚未配置外部 MCP"
      reason="内置 loci-market 始终可用；外部 server 写入 data/mcp.json"
      eta="点「添加」或手动编辑 mcp.json"
    />
    <p class="form-hint">
      内置 <code>loci-market</code> 无需配置，Skill 写 <code>mcp_servers: [loci-market]</code> 即可。
      外部 server 仍写 <code>data/mcp.json</code>（Cursor 兼容）。
    </p>
  </Sheet>

  <el-dialog v-model="mcpFormOpen" title="添加 MCP Server" :width="dialogWidth()" destroy-on-close>
    <el-form label-position="top" @submit.prevent="submitMcp">
      <div class="form-grid">
        <el-form-item label="名称" required>
          <el-input v-model.trim="mcpForm.name" placeholder="my-data-source" />
        </el-form-item>
        <el-form-item label="专用代理">
          <el-input v-model.trim="mcpForm.proxy_url" placeholder="http://172.17.0.1:7890" />
        </el-form-item>
        <el-form-item label="URL" required class="full-span">
          <el-input v-model.trim="mcpForm.url" placeholder="https://mcp.example.com" />
        </el-form-item>
        <el-form-item label="Token（可选）" class="full-span">
          <el-input
            v-model.trim="mcpForm.token"
            type="password"
            autocomplete="off"
            placeholder="Bearer token，公开 server 留空"
            show-password
          />
        </el-form-item>
        <el-form-item label="备注" class="full-span">
          <el-input v-model.trim="mcpForm.note" placeholder="用途说明" />
        </el-form-item>
        <el-form-item class="full-span">
          <el-checkbox v-model="mcpForm.verify">保存时握手校验（推荐）</el-checkbox>
        </el-form-item>
      </div>
      <p class="form-hint">
        保存时发起 tools/list 发现工具列表；校验失败不入库。Token 用 AES-256-GCM 加密存储，只回末四位。
      </p>
    </el-form>
    <template #footer>
      <el-button @click="mcpFormOpen = false">取消</el-button>
      <el-button type="primary" :disabled="busy" @click="submitMcp">保存并发现工具</el-button>
    </template>
  </el-dialog>
</template>
