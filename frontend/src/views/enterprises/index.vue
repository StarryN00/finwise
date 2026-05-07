<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>企业管理</span>
          <el-button type="primary" @click="showAddDialog = true">
            <el-icon><Plus /></el-icon>
            添加企业
          </el-button>
        </div>
      </template>
      <el-table :data="[]" stripe style="width: 100%">
        <el-table-column prop="name" label="企业名称" />
        <el-table-column prop="taxId" label="纳税人识别号" />
        <el-table-column prop="type" label="企业类型" />
        <el-table-column prop="status" label="状态" />
        <el-table-column label="操作" width="180" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'

const showAddDialog = ref(false)
</script>

<style scoped>
.page-container {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>