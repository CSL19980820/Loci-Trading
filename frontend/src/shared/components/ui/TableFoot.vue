<script setup lang="ts">
withDefaults(
  defineProps<{
    total: number
    pageSize?: number
    /** Hide when total fits on one page. */
    hideSinglePage?: boolean
  }>(),
  {
    pageSize: 20,
    hideSinglePage: true,
  },
)

const currentPage = defineModel<number>('page', { default: 1 })
</script>

<template>
  <div v-if="!hideSinglePage || total > pageSize" class="table-foot">
    <el-pagination
      v-model:current-page="currentPage"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      background
      size="small"
    />
  </div>
</template>
