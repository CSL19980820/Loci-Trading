<template>
  <dialog ref="dialog" class="trade-dialog" aria-labelledby="trade-title" @close="model = false">
    <form class="trade-form" method="dialog" @submit.prevent="submit">
      <div class="dialog-heading">
        <h2 id="trade-title">记成交</h2>
        <button class="icon-button" type="button" aria-label="关闭" @click="close">×</button>
      </div>
      <fieldset>
        <label>
          动作
          <select v-model="form.action">
            <option value="BUY">买</option>
            <option value="SELL">卖</option>
          </select>
        </label>
        <label>
          代码
          <input v-model.trim="form.code" inputmode="numeric" pattern="\d{6}" maxlength="6" required />
        </label>
        <label>
          名称
          <input v-model.trim="form.name" />
        </label>
        <label>
          股数
          <input v-model.number="form.shares" type="number" min="1" required />
        </label>
        <label>
          价
          <input v-model.number="form.price" type="number" min="0" step="0.001" required />
        </label>
        <label>
          日期
          <input v-model="form.occurred_on" type="date" />
        </label>
      </fieldset>
      <label class="wide-label">
        备注
        <textarea v-model.trim="form.reason" rows="2" />
      </label>
      <p v-if="submitError" class="form-error" role="alert">{{ submitError }}</p>
      <div class="dialog-actions">
        <button class="quiet-button" type="button" @click="close">取消</button>
        <button class="primary-button" type="submit" :disabled="submitting">
          {{ submitting ? '…' : '写入' }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { usePalaceStore } from '@/stores/palace'
import type { TradePayload } from '@/types'

const model = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [] }>()
const store = usePalaceStore()
const route = useRoute()
const dialog = ref<HTMLDialogElement>()
const submitting = ref(false)
const submitError = ref('')
const form = reactive<TradePayload>({
  action: 'BUY',
  code: '',
  name: '',
  shares: 100,
  price: 0,
  occurred_on: new Date().toISOString().slice(0, 10),
  reason: '',
})

watch(model, (isOpen) => {
  if (isOpen && dialog.value && !dialog.value.open) dialog.value.showModal()
  if (!isOpen && dialog.value?.open) dialog.value.close()
})

function close(): void {
  model.value = false
}

async function submit(): Promise<void> {
  if (!/^\d{6}$/.test(form.code)) {
    submitError.value = '代码须 6 位数字'
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