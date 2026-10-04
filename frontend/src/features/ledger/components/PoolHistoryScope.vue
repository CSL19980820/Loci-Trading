<script setup lang="ts">
import { useId } from 'vue'
import { Label } from '@/shared/components/ui/label'
import { Switch } from '@/shared/components/ui/switch'

const enabled = defineModel<boolean>({ required: true })
const id = useId()
</script>

<template>
  <div class="pool-history-scope">
    <div class="pool-history-scope__control">
      <Switch :id="id" v-model="enabled" :aria-describedby="`${id}-hint`" />
      <Label :for="id">包含历史回填</Label>
    </div>
    <span :id="`${id}-hint`" class="pool-history-scope__hint">
      {{ enabled ? '回填记录单独标识，不代表当日实时选出' : '默认不含回填；战法足迹包含历史记录' }}
    </span>
  </div>
</template>

<style scoped>
.pool-history-scope { display:flex; flex-wrap:wrap; align-items:center; gap:4px 14px; min-width:0; }
.pool-history-scope__control { display:flex; flex:none; align-items:center; gap:8px; min-height:32px; }
.pool-history-scope__control :deep(label) { cursor:pointer; font-size:var(--fs-ui); }
.pool-history-scope__hint { color:var(--text-tertiary); font-size:var(--fs-aux); line-height:1.5; overflow-wrap:anywhere; }
@media (max-width:767px) {
  .pool-history-scope { margin-top:8px; gap:2px 10px; }
  .pool-history-scope__control { min-height:36px; }
}
</style>
