<script setup lang="ts">
import { BookOpen, RefreshCw } from '@lucide/vue'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Skeleton } from '@/shared/components/ui/skeleton'
import type { AgentRunDetail } from '@/shared/types/stock_agents'
import { agentTime, phaseName, statusName } from '../agentFormat'
import AgentReportDocument from './AgentReportDocument.vue'

defineProps<{ open: boolean; detail: AgentRunDetail | null; loading?: boolean; error?: string }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; retry: [] }>()
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent unstyled class="agent-run-dialog">
      <DialogHeader class="agent-run-dialog__head">
        <div class="agent-run-dialog__title"><BookOpen aria-hidden="true" /><DialogTitle>工作日记详情</DialogTitle></div>
        <DialogDescription>{{ detail ? `${phaseName(detail.phase)} · ${agentTime(detail.started_at)} · ${statusName(detail.status)} · 模拟账户` : '读取本轮保存的判断、执行与证据' }}</DialogDescription>
      </DialogHeader>
      <div class="history-sheet__body" data-agent-workspace-scroll role="region" aria-label="工作日记完整内容" tabindex="0">
        <div v-if="loading" class="agent-run-dialog__loading" aria-label="正在读取日记"><Skeleton v-for="n in 8" :key="n" class="h-12 w-full" /></div>
        <Alert v-else-if="error" variant="destructive"><AlertTitle class="line-clamp-none">{{ error }}</AlertTitle><Button access="read" variant="outline" size="sm" @click="emit('retry')"><RefreshCw />重新读取</Button></Alert>
        <AgentReportDocument v-else-if="detail" :run="detail" />
      </div>
    </DialogContent>
  </Dialog>
</template>

<style>
.agent-run-dialog {
  position:fixed; z-index:var(--z-popup); top:16px; left:50%; transform:translateX(-50%);
  width:min(1120px,calc(100vw - 32px)); max-width:calc(100vw - 32px);
  height:calc(100dvh - 32px); max-height:calc(100dvh - 32px);
  display:flex; flex-direction:column; min-height:0; gap:0; padding:0; overflow:hidden;
  border:1px solid var(--border-subtle); border-radius:14px; background:var(--surface); color:var(--text-primary);
  box-shadow:0 20px 80px #0003; outline:none;
}
.agent-run-dialog__head { flex:none; padding:20px 56px 16px 28px; border-bottom:1px solid var(--border-subtle); text-align:left; }
.agent-run-dialog__title { display:flex; align-items:center; gap:10px; }
.agent-run-dialog__title svg { width:20px; height:20px; color:var(--seal); }
.agent-run-dialog .history-sheet__body { flex:1 1 0%; min-height:0; overflow:auto; overscroll-behavior:contain; padding:24px 28px 32px; }
.agent-run-dialog .history-sheet__body:focus-visible { outline:2px solid var(--seal); outline-offset:-2px; }
.agent-run-dialog__loading { display:grid; gap:16px; }
@media(max-width:767px) { .agent-run-dialog__head { padding:16px 44px 12px 16px; } .agent-run-dialog .history-sheet__body { padding:16px; } }
</style>
