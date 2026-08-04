<script setup lang="ts">
import { ref } from 'vue'

import { installSkill } from '@/shared/api/quant'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { toErrorMessage } from '@/shared/lib/errors'

const emit = defineEmits<{
  installed: []
  notice: [message: string]
  error: [message: string]
}>()

const busy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function pickFile(): void {
  fileInput.value?.click()
}

async function onUpload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  busy.value = true
  try {
    const installed = await installSkill(file)
    emit('notice', `已安装技能 ${installed.slug}`)
    emit('installed')
  } catch (caught: unknown) {
    emit('error', toErrorMessage(caught, '安装失败'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="publish">
    <Sheet title="安装 Skill 包" chip="zip">
      <template #actions>
        <el-button type="primary" :loading="busy" @click="pickFile">选择 zip</el-button>
      </template>
      <!-- 原生 file input：浏览器选文件能力，隐藏后由上方按钮触发 -->
      <input
        ref="fileInput"
        type="file"
        accept=".zip"
        hidden
        @change="onUpload"
      />
    </Sheet>
  </div>
</template>

<style scoped>
.publish {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
</style>
