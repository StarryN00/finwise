<template>
  <div class="dashboard">
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-icon" style="background: #409eff">
            <el-icon :size="32"><OfficeBuilding /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">12</div>
            <div class="stat-label">服务企业数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-icon" style="background: #67c23a">
            <el-icon :size="32"><Document /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">256</div>
            <div class="stat-label">本月发票数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-icon" style="background: #e6a23c">
            <el-icon :size="32"><Coin /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">18</div>
            <div class="stat-label">待申报任务</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-icon" style="background: #f56c6c">
            <el-icon :size="32"><DataLine /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">5</div>
            <div class="stat-label">融资需求</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>最近操作记录</span>
          </template>
          <el-timeline>
            <el-timeline-item timestamp="2024-05-07 16:30" placement="top">
              <p>完成 xxx 公司的增值税申报</p>
            </el-timeline-item>
            <el-timeline-item timestamp="2024-05-07 14:20" placement="top">
              <p>导入银行对账单 23 条</p>
            </el-timeline-item>
            <el-timeline-item timestamp="2024-05-07 10:15" placement="top">
              <p>生成 xxx 公司财务分析报告</p>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>快捷操作</span>
          </template>
          <div class="quick-actions">
            <el-button type="primary" plain @click="$router.push('/invoices')">
              <el-icon><Upload /></el-icon>
              导入发票
            </el-button>
            <el-button type="success" plain @click="$router.push('/tax-filing')">
              <el-icon><Document /></el-icon>
              发起申报
            </el-button>
            <el-button type="warning" plain @click="$router.push('/reports')">
              <el-icon><DataLine /></el-icon>
              生成报告
            </el-button>
            <el-button type="info" plain @click="$router.push('/enterprises')">
              <el-icon><Plus /></el-icon>
              添加企业
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { OfficeBuilding, Document, Coin, DataLine, Upload, Plus } from '@element-plus/icons-vue'
</script>

<style scoped>
.dashboard {
  width: 100%;
}

.stat-card {
  display: flex;
  align-items: center;
  padding: 20px;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  margin-right: 20px;
}

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 5px;
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
</style>