<template>
  <section class="output-grid">
    <article v-for="item in outputs" :key="item.title" class="output-card" :class="{ disabled: item.disabled }">
      <div>
        <h2 class="section-title">{{ item.title }}</h2>
        <p class="caption">{{ item.description }}</p>
      </div>
      <StatusTag :status="item.status" />
      <el-button :disabled="item.disabled" type="primary">{{ item.action }}</el-button>
    </article>
  </section>
</template>

<script setup>
import StatusTag from '../components/StatusTag.vue'

const outputs = [
  { title: '申报辅助 Excel', description: '增值税及附加税复制表', status: 'READY_TO_EXPORT', action: '导出 Excel' },
  { title: '老板版月度简报', description: '经营概览、税务概览、异常事项', status: 'READY_TO_EXPORT', action: '生成简报' },
  { title: '完整健康诊断报告', description: '偿债、盈利、现金流、税务风险 8 段诊断', status: 'DATA_INSUFFICIENT', action: '补齐数据', disabled: true },
]
</script>

<style scoped>
.output-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.output-card {
  display: grid;
  align-content: space-between;
  gap: 18px;
  min-height: 190px;
  padding: 18px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.output-card.disabled {
  background: var(--fw-surface-muted);
}

.output-card .caption {
  margin: 8px 0 0;
}

@media (max-width: 960px) {
  .output-grid {
    grid-template-columns: 1fr;
  }
}
</style>
