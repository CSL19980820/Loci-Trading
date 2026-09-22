<script setup lang="ts">
import { reactive, ref } from 'vue'
import { toast } from 'vue-sonner'

import { notifyUser } from '@/shared/api/admin'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Textarea } from '@/shared/components/ui/textarea'
import UiField from '@/shared/components/ui/UiField.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AdminUserItem } from '@/shared/types/admin'

const props = defineProps<{
  visible: boolean
  user: AdminUserItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'sent'): void
}>()

const form = reactive({
  title: '',
  body: '',
})
const loading = ref(false)

function onClose(): void {
  form.title = ''
  form.body = ''
  emit('update:visible', false)
}

/** 点遮罩 / 按 Esc 关闭 = 取消，清掉未发送的草稿 */
function onOpenChange(next: boolean): void {
  if (!next) onClose()
}

async function onSubmit(): Promise<void> {
  if (!props.user) return
  if (!form.title.trim()) {
    toast.warning('请输入通知标题')
    return
  }

  loading.value = true
  try {
    await notifyUser(props.user.id, form.title.trim(), form.body.trim())
    toast.success('通知已发送')
    emit('sent')
    onClose()
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '发送通知失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Dialog :open="visible" @update:open="onOpenChange">
    <DialogContent
      class="admin-form-dialog w-[min(92vw,560px)] max-w-none gap-3 rounded-[var(--radius)] p-4 sm:max-w-none"
    >
      <DialogHeader class="gap-1 text-left">
        <DialogTitle class="admin-form-dialog__title">
          {{ `发送站内通知 - ${user?.display_name || user?.username}` }}
        </DialogTitle>
      </DialogHeader>

      <div class="admin-form-dialog__body notify-form">
        <UiField label="标题" required>
          <Input
            v-model="form.title"
            placeholder="如：系统重要通知"
            maxlength="120"
          />
        </UiField>
        <UiField label="正文">
          <Textarea
            v-model="form.body"
            :rows="4"
            placeholder="请输入通知详细内容（支持纯文本）"
            maxlength="2000"
          />
        </UiField>
      </div>

      <DialogFooter class="admin-form-dialog__footer">
        <Button access="read" variant="outline" @click="onClose">取消</Button>
        <Button :disabled="loading" @click="onSubmit">发送通知</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.notify-form {
  display: grid;
  gap: var(--gap-2);
}
</style>

<style scoped src="./AdminDialog.css" />
