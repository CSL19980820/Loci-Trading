<script setup lang="ts">
import { ref } from 'vue'
import { Eye, EyeOff } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { resetUserPassword } from '@/shared/api/admin'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiField from '@/shared/components/ui/UiField.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminUserItem } from '@/shared/types/admin'

const props = defineProps<{
  visible: boolean
  user: AdminUserItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'saved'): void
}>()

const newPassword = ref('')
const revealed = ref(false)
const loading = ref(false)

function onClose(): void {
  newPassword.value = ''
  revealed.value = false
  emit('update:visible', false)
}

/** 点遮罩 / 按 Esc 关闭 = 取消，并抹掉已输入的口令 */
function onOpenChange(next: boolean): void {
  if (!next) onClose()
}

async function onSubmit(): Promise<void> {
  if (!props.user) return
  if (!newPassword.value || newPassword.value.length < 8) {
    toast.warning('新密码长度不能少于 8 位')
    return
  }

  const confirmed = await confirmDangerous(
    `确定要为用户「${props.user.display_name || props.user.username}」重置密码吗？该用户的全部现有会话将被强制断开，且下次登录需强制修改密码。`,
    '危险操作：重置密码',
    '确认重置',
  )
  if (!confirmed) return

  loading.value = true
  try {
    await resetUserPassword(props.user.id, newPassword.value)
    toast.success('密码重置成功')
    emit('saved')
    onClose()
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '重置密码失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Dialog :open="visible" @update:open="onOpenChange">
    <DialogContent
      class="admin-form-dialog w-[min(92vw,480px)] max-w-none gap-3 rounded-[var(--radius)] p-4 sm:max-w-none"
    >
      <DialogHeader class="gap-1 text-left">
        <DialogTitle class="admin-form-dialog__title">
          {{ `重置用户密码 - ${user?.display_name || user?.username}` }}
        </DialogTitle>
      </DialogHeader>

      <div class="admin-form-dialog__body">
        <UiField label="新密码">
          <div class="relative">
            <Input
              v-model="newPassword"
              :type="revealed ? 'text' : 'password'"
              class="pr-9"
              placeholder="请输入至少 8 位新密码"
              autocomplete="new-password"
            />
            <Button
              variant="ghost"
              size="icon-xs"
              class="absolute top-1/2 right-1 -translate-y-1/2"
              :aria-label="revealed ? '隐藏新密码' : '显示新密码'"
              :aria-pressed="revealed"
              @click="revealed = !revealed"
            >
              <EyeOff v-if="revealed" class="size-3.5" aria-hidden="true" />
              <Eye v-else class="size-3.5" aria-hidden="true" />
            </Button>
          </div>
        </UiField>
      </div>

      <DialogFooter class="admin-form-dialog__footer">
        <Button access="read" variant="outline" @click="onClose">取消</Button>
        <Tooltip :delay-duration="200">
          <TooltipTrigger as-child>
            <Button variant="destructive" :disabled="loading" @click="onSubmit">确认重置</Button>
          </TooltipTrigger>
          <TooltipContent>重置后该用户全部会话立即注销，下次登录须改密</TooltipContent>
        </Tooltip>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped src="./AdminDialog.css" />
