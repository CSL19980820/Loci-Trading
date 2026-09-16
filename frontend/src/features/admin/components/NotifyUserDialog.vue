<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { notifyUser } from '@/shared/api/admin'
import type { AdminUserItem } from '@/shared/types/admin'
import { toErrorMessage } from '@/shared/lib/errors'

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

async function onSubmit(): Promise<void> {
  if (!props.user) return
  if (!form.title.trim()) {
    ElMessage.warning('请输入通知标题')
    return
  }

  loading.value = true
  try {
    await notifyUser(props.user.id, form.title.trim(), form.body.trim())
    ElMessage.success('通知已发送')
    emit('sent')
    onClose()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '发送通知失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    class="admin-form-dialog dialog-body--scroll"
    :model-value="visible"
    :title="`发送站内通知 - ${user?.display_name || user?.username}`"
    width="min(92vw, 560px)"
    @close="onClose"
  >
    <el-form label-position="right" label-width="6.5em" size="small">
      <el-form-item label="标题" required>
        <el-input v-model="form.title" placeholder="如：系统重要通知" maxlength="120" show-word-limit />
      </el-form-item>
      <el-form-item label="正文">
        <el-input
          v-model="form.body"
          type="textarea"
          :rows="4"
          placeholder="请输入通知详细内容（支持纯文本）"
          maxlength="2000"
          show-word-limit
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="onClose">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">发送通知</el-button>
    </template>
  </el-dialog>
</template>

<style scoped src="./AdminDialog.css" />
