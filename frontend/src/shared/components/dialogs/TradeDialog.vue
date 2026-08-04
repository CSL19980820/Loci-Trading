<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { dialogWidth, localToday } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'
import type { TradePayload } from '@/shared/types/palace'

const model = defineModel<boolean>({ default: false })
const props = defineProps<{
  presetCode?: string
  presetName?: string
}>()
const emit = defineEmits<{ saved: [] }>()
const store = usePalaceStore()
const route = useRoute()
const submitting = ref(false)
const submitError = ref('')
const width = computed(() => dialogWidth())
const form = reactive<TradePayload>({
  action: 'BUY',
  code: '',
  name: '',
  shares: 100,
  price: 0,
  occurred_on: localToday(),
  reason: '',
})

watch(model, (isOpen) => {
  if (!isOpen) return
  form.action = 'BUY'
  form.code = props.presetCode ?? ''
  form.name = props.presetName ?? ''
  form.shares = 100
  form.price = 0
  form.occurred_on = localToday()
  form.reason = ''
  submitError.value = ''
})

function close(): void {
  model.value = false
}

async function submit(): Promise<void> {
  if (!/^\d{6}$/.test(form.code)) {
    submitError.value = '代码须 6 位数字'
    return
  }
  if (!(form.shares > 0)) {
    submitError.value = '股数须大于 0'
    return
  }
  if (!(form.price > 0)) {
    submitError.value = '价格须大于 0'
    return
  }
  submitting.value = true
  submitError.value = ''
  try {
    await store.addTrade({ ...form }, route)
    emit('saved')
    close()
  } catch (caught: unknown) {
    submitError.value = caught instanceof Error ? caught.message : '写入失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="model"
    title="记成交"
    :width="width"
    destroy-on-close
    @closed="submitError = ''"
  >
    <el-form label-position="top" @submit.prevent="submit">
      <div class="form-grid">
        <el-form-item label="动作">
          <el-select v-model="form.action">
            <el-option label="买" value="BUY" />
            <el-option label="卖" value="SELL" />
          </el-select>
        </el-form-item>
        <el-form-item label="代码" required>
          <el-input v-model.trim="form.code" maxlength="6" inputmode="numeric" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model.trim="form.name" />
        </el-form-item>
        <el-form-item label="股数" required>
          <el-input-number v-model="form.shares" :min="1" :controls="false" class="full" />
        </el-form-item>
        <el-form-item label="价" required>
          <el-input-number v-model="form.price" :min="0" :step="0.001" :controls="false" class="full" />
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker
            v-model="form.occurred_on"
            type="date"
            value-format="YYYY-MM-DD"
            class="full"
          />
        </el-form-item>
      </div>
      <el-form-item label="备注">
        <el-input v-model.trim="form.reason" type="textarea" :rows="2" />
      </el-form-item>
      <el-alert v-if="submitError" :title="submitError" type="error" show-icon :closable="false" />
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">写入</el-button>
    </template>
  </el-dialog>
</template>
