<script setup lang="ts">
import TextField from '@/shared/components/ui/app/TextField.vue'
defineProps<{ disabled?: boolean }>()
const notes = defineModel<string>({ required: true })
</script>
<template>
  <div class="consult-context-editor">
    <h4>我的实际持仓 / 执行偏差</h4>
    <p>选填，发送咨询时随话题保存。这里只提供咨询背景，不会修改模拟账户。</p>
    <TextField v-model="notes" aria-label="实际持仓背景" :disabled="disabled" type="textarea" :autosize="{ minRows: 7, maxRows: 16 }" maxlength="12000" placeholder="股票名称或代码、实际股数、成本、买入日期、可用现金，以及和模拟操作的不同。" />
  </div>
</template>
<style scoped>
.consult-context-editor { display:flex; flex-direction:column; gap:10px; min-width:0; }
h4 { margin:0; font-size:var(--fs-ui); font-weight:600; }
p { margin:0; color:var(--muted); font-size:var(--fs-aux); line-height:1.65; }
</style>
