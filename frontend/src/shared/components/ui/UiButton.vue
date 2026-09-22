<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { Spinner } from '@/shared/components/ui/spinner'
withDefaults(defineProps<{
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
  size?: 'default' | 'sm' | 'lg' | 'icon'
  disabled?: boolean
  loading?: boolean
  type?: 'button' | 'submit' | 'reset'
}>(), {variant:'default',size:'default',disabled:false,loading:false,type:'button'})
const emit = defineEmits<{ click:[event:MouseEvent] }>()
</script>
<template>
  <Button :type="type" :variant="variant" :size="size" :disabled="disabled || loading" :aria-busy="loading || undefined" class="ui-button" @click.stop="emit('click',$event)"><Spinner v-if="loading" /><slot /></Button>
</template>
