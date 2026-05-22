<template>
  <div class="init-grid">
    <section class="panel">
      <h2 class="section-title">基础信息</h2>
      <el-form label-width="110px" class="init-form">
        <el-form-item label="企业名称"><el-input model-value="苏州样例科技有限公司" /></el-form-item>
        <el-form-item label="纳税人类型"><el-select model-value="GENERAL"><el-option label="一般纳税人" value="GENERAL" /></el-select></el-form-item>
        <el-form-item label="所属行业"><el-input model-value="制造业" /></el-form-item>
      </el-form>
    </section>
    <section class="panel">
      <h2 class="section-title">期初资产负债表</h2>
      <el-upload drag action="#" :auto-upload="false">
        <span>上传资产负债表 Excel</span>
      </el-upload>
    </section>
    <section class="panel">
      <h2 class="section-title">期初利润表</h2>
      <el-upload drag action="#" :auto-upload="false">
        <span>上传利润表 Excel</span>
      </el-upload>
    </section>
    <section class="panel">
      <h2 class="section-title">校验结果</h2>
      <div class="validation-list">
        <MetricCard label="资产负债平衡" value="通过" subtext="资产 = 负债 + 所有者权益" tone="success" />
        <MetricCard label="利润表完整性" value="待校验" subtext="上传后自动检查关键科目" tone="warning" />
      </div>
    </section>
  </div>
</template>

<script setup>
import MetricCard from '../components/MetricCard.vue'
</script>

<style scoped>
.init-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.panel {
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.init-form {
  margin-top: 16px;
}

.validation-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

@media (max-width: 960px) {
  .init-grid,
  .validation-list {
    grid-template-columns: 1fr;
  }
}
</style>
