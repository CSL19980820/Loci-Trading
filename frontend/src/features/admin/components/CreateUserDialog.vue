<script setup lang="ts">
/**
 * 管理员代建账号。本系统**不开放自助注册**（后端 `LOCI_ALLOW_SIGNUP` 默认关），
 * 所以这是全站唯一的开号入口——表单走 `BasicForm` 契约，不再自绘 label 行。
 *
 * 初始口令由管理员当场设定并线下转交，新号一律带 `must_change_password`：
 * 管理员长期知道别人的常用口令，是安全事故的起点。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { createAdminUser } from '@/shared/api/admin'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import { toErrorMessage } from '@/shared/lib/errors'
import type { CreateAdminUserPayload } from '@/shared/types/admin'
import type { Role } from '@/shared/types/auth'
import { CREATABLE_STATUS_OPTIONS, ROLE_OPTIONS } from '../lib/adminDict'

const open = defineModel<boolean>({ required: true })

const emit = defineEmits<{ created: [] }>()

const formRef = ref<InstanceType<typeof BasicForm>>()
const submitting = ref(false)

/** 每次开窗都从这份初值起步，避免上一次输入的口令留在内存里被下一次误提交。 */
function blankForm(): Record<string, unknown> {
  return {
    username: '',
    password: '',
    display_name: '',
    email: '',
    role: 'member',
    status: 'active',
  }
}

const model = ref<Record<string, unknown>>(blankForm())

const schemas: BasicFormSchema[] = [
  {
    field: 'username',
    label: '登录账号',
    componentProps: { placeholder: '字母 / 数字 / 下划线', maxlength: 32 },
    rules: [{ required: true, message: '填登录账号', trigger: 'change' }],
  },
  {
    field: 'display_name',
    label: '用户名称',
    componentProps: { placeholder: '不填则与登录账号相同', maxlength: 64 },
  },
  {
    field: 'password',
    label: '初始口令',
    componentProps: { type: 'password', showPassword: true, placeholder: '至少 8 位', autocomplete: 'new-password' },
    hint: '首次登录须改密',
    rules: [
      { required: true, message: '填初始口令', trigger: 'change' },
      { min: 8, message: '至少 8 位', trigger: 'change' },
    ],
  },
  {
    field: 'email',
    label: '邮箱',
    componentProps: { placeholder: '选填，填了即可用邮箱登录', maxlength: 254 },
  },
  {
    field: 'role',
    label: '角色',
    component: 'select',
    componentProps: { options: [...ROLE_OPTIONS] },
  },
  {
    field: 'status',
    label: '账号状态',
    component: 'select',
    componentProps: { options: [...CREATABLE_STATUS_OPTIONS] },
    tooltip: '停用状态下账号已建但无法登录，适合先开号后放行',
  },
]

function onClosed(): void {
  model.value = blankForm()
  formRef.value?.resetForm()
}

async function onSubmit(): Promise<void> {
  const values = await formRef.value?.submit()
  if (!values) return

  const payload: CreateAdminUserPayload = {
    username: String(values.username || '').trim(),
    password: String(values.password || ''),
    display_name: String(values.display_name || '').trim(),
    email: String(values.email || '').trim(),
    role: String(values.role || 'member') as Role,
    status: values.status === 'disabled' ? 'disabled' : 'active',
  }

  submitting.value = true
  try {
    await createAdminUser(payload)
    ElMessage.success(`账号「${payload.username}」已建好，请线下转交初始口令`)
    emit('created')
    open.value = false
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '新增用户失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    class="admin-form-dialog dialog-body--scroll"
    v-model="open"
    title="新增用户"
    width="min(92vw, 560px)"
    destroy-on-close
    @closed="onClosed"
  >
    <BasicForm
      ref="formRef"
      v-model="model"
      :schemas="schemas"
      :columns="2"
      :input-debounce-ms="0"
    />

    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">建号</el-button>
    </template>
  </el-dialog>
</template>

<style scoped src="./AdminDialog.css" />
