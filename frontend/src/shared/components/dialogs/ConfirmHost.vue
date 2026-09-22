<script setup lang="ts">
import { computed } from 'vue'
import { TriangleAlert } from '@lucide/vue'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/shared/components/ui/alert-dialog'
import { Button } from "@/shared/components/ui/button"
import { pendingConfirm, settleConfirm } from '@/shared/lib/confirm'

/**
 * `confirmAction()` 的宿主：把模块级待确认请求渲染成一个 AlertDialog。
 * 只在 `App.vue` 挂一次。缺了它，所有 `confirmDangerous` / `alertDialog` 的 Promise 都不会 settle。
 *
 * 危险操作带一枚琥珀 / 印章红图标方块，主按钮实心红；普通确认无图标。
 */
const request = computed(() => pendingConfirm.value)
const open = computed({
  get: () => pendingConfirm.value !== null,
  set: (next: boolean) => {
    // 点遮罩 / 按 Esc 关闭 = 取消
    if (!next) settleConfirm(false)
  },
})
</script>

<template>
  <AlertDialog v-model:open="open">
    <AlertDialogContent class="confirm-host gap-4 rounded-xl border-line bg-raised p-5 shadow-lg sm:max-w-[440px]">
      <AlertDialogHeader class="gap-1 text-left" :class="{ 'confirm-host__head--icon': request?.danger }">
        <span v-if="request?.danger" class="confirm-host__icon" aria-hidden="true"><TriangleAlert /></span>
 <div class="min-w-0 flex flex-col gap-1.5">
   <AlertDialogTitle class="text-[16px] font-semibold tracking-tight text-ink">{{ request?.title ?? '确认' }}</AlertDialogTitle>
   <AlertDialogDescription class="text-ui leading-relaxed whitespace-pre-line text-ink-2">
     {{ request?.message }}
   </AlertDialogDescription>
        </div>
      </AlertDialogHeader>
      <AlertDialogFooter class="gap-2 max-sm:flex-col-reverse max-sm:[&>button]:h-11 max-sm:[&>button]:w-full">
 <AlertDialogCancel v-if="!request?.alertOnly" class="mt-0" @click="settleConfirm(false)">
   {{ request?.cancelText ?? '取消' }}
        </AlertDialogCancel>
        <Button
   :class="request?.danger ? 'bg-stamp text-white shadow-[var(--shadow-inset-highlight),var(--shadow-xs)] hover:bg-stamp/90 focus-visible:ring-destructive/25' : undefined"
   @click="settleConfirm(true)"
        >
          {{ request?.confirmText ?? '确认' }}
 </Button>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

<style scoped>
.confirm-host__head--icon {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--gap-3);
  align-items: start;
}

.confirm-host__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-lg);
  background: var(--stamp-soft);
  color: var(--stamp);
}

.confirm-host__icon :deep(svg) {
  width: 20px;
  height: 20px;
}
</style>
