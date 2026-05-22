<script setup>
const props = defineProps({
  status: {
    type: String,
    default: 'PENDING_IMPORT',
  },
})

const statusMap = {
  PENDING_IMPORT: ['待导入', 'warning'],
  PENDING: ['待确认', 'warning'],
  PENDING_CONFIRMATION: ['待确认', 'warning'],
  CONFIRMED: ['已确认', 'success'],
  READY_TO_EXPORT: ['可导出', 'primary'],
  DRAFT: ['草稿', 'primary'],
  EXPORTED: ['已导出', 'info'],
  DATA_INSUFFICIENT: ['数据不足', 'danger'],
}

const resolved = statusMap[props.status] || [props.status, 'info']
</script>

<template>
  <el-tag :type="resolved[1]" effect="light" round>
    {{ resolved[0] }}
  </el-tag>
</template>
