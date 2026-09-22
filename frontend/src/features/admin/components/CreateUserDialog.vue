<script setup lang="ts">
/**
 * 管理员代建账号。本系统**不开放自助注册**（后端 `LOCI_ALLOW_SIGNUP` 默认关），
 * 所以这是全站唯一的开号入口——表单走 `BasicForm` 契约，不再自绘 label 行。
 *
 * 初始口令由管理员当场设定并线下转交，新号一律带 `must_change_password`：
 * 管理员长期知道别人的常用口令，是安全事故的起点。
 */
import { ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { createAdminUser } from '@/shared/api/admin'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
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
    role: 'visitor',
    status: 'active',
  }
}

const model = ref<Record<string, unknown>>(blankForm())
watch(open, value => { if (!value) model.value = blankForm() })

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

/** 弹层关闭（含 Esc / 点遮罩）后清空：口令不留到下一次开窗 */
function onOpenChange(next: boolean): void {
  if (next) return
  open.value = false
  onClosed()
}

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  const values = await formRef.value?.submit()
  if (!values) return

  const payload: CreateAdminUserPayload = {
    username: String(values.username || '').trim(),
    password: String(values.password || ''),
    display_name: String(values.display_name || '').trim(),
    email: String(values.email || '').trim(),
    role: String(values.role || 'visitor') as Role,
    status: values.status === 'disabled' ? 'disabled' : 'active',
  }

  submitting.value = true
  try {
    await createAdminUser(payload)
    toast.success(`账号「${payload.username}」已建好，请线下转交初始口令`)
    emit('created')
    open.value = false
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '新增用户失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="onOpenChange">
    <DialogContent
      class="admin-form-dialog w-[min(92vw,760px)] max-w-none gap-3 rounded-[var(--radius)] p-4 sm:max-w-none"
    >
      <DialogHeader class="gap-1 text-left">
        <DialogTitle class="admin-form-dialog__title">新增用户</DialogTitle>
      </DialogHeader>

      <div class="admin-form-dialog__body">
        <BasicForm
          ref="formRef"
          v-model="model"
          :schemas="schemas"
          :columns="2"
          :input-debounce-ms="0"
        />
      </div>

      <DialogFooter class="admin-form-dialog__footer">
        <Button access="read" variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" @click="onSubmit">建号</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped src="./AdminDialog.css" />
