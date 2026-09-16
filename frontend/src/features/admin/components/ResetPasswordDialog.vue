<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { resetUserPassword } from '@/shared/api/admin'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { AdminUserItem } from '@/shared/types/admin'
import { toErrorMessage } from '@/shared/lib/errors'

const props = defineProps<{
  visible: boolean
  user: AdminUserItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'saved'): void
}>()

const newPassword = ref('')
const loading = ref(false)

function onClose(): void {
  newPassword.value = ''
  emit('update:visible', false)
}

async function onSubmit(): Promise<void> {
  if (!props.user) return
  if (!newPassword.value || newPassword.value.length < 8) {
    ElMessage.warning('新密码长度不能少于 8 位')
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
    ElMessage.success('密码重置成功')
    emit('saved')
    onClose()
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '重置密码失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    class="admin-form-dialog dialog-body--scroll"
    :model-value="visible"
    :title="`重置用户密码 - ${user?.display_name || user?.username}`"
    width="min(92vw, 480px)"
    @close="onClose"
  >
    <el-form label-position="right" label-width="6.5em" size="small">
      <el-form-item label="新密码">
        <el-input
          v-model="newPassword"
          type="password"
          show-password
          placeholder="请输入至少 8 位新密码"
          autocomplete="new-password"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="onClose">取消</el-button>
      <el-tooltip content="重置后该用户全部会话立即注销，下次登录须改密" placement="top">
        <el-button type="danger" :loading="loading" @click="onSubmit">确认重置</el-button>
      </el-tooltip>
    </template>
  </el-dialog>
</template>


<style scoped src="./AdminDialog.css" />
