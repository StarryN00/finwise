<template>
  <section class="step-grid">
    <article v-for="(step, index) in steps" :key="step" class="step-card">
      <span>{{ index + 1 }}</span>
      <strong>{{ step }}</strong>
    </article>
  </section>

  <section class="workspace-grid">
    <div class="panel">
      <h2 class="section-title">缺失资料清单</h2>
      <ul class="checklist">
        <li v-for="item in workspace.missingChecklist" :key="item.label">
          <el-checkbox :model-value="item.done" disabled>{{ item.label }}</el-checkbox>
        </li>
      </ul>
    </div>
    <div class="panel">
      <h2 class="section-title">确认进度</h2>
      <MetricCard label="待人工确认" value="3" subtext="包含未匹配流水、发票和规则分类" tone="warning" />
    </div>
  </section>
</template>

<script setup>
import MetricCard from '../components/MetricCard.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const steps = ['导入资料', '解析结果', '匹配确认', '账目明细', '预估报表', '申报辅助', '老板简报']
</script>

<style scoped>
.step-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}

.step-card,
.panel {
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.step-card {
  min-height: 82px;
  padding: 12px;
}

.step-card span {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--fw-radius-sm);
  color: var(--fw-brand-dark);
  background: var(--fw-brand-soft);
  font-size: 12px;
  font-weight: 800;
}

.step-card strong {
  display: block;
  margin-top: 10px;
  font-size: 13px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
}

.panel {
  padding: 16px;
}

.checklist {
  display: grid;
  gap: 8px;
  padding: 0;
  margin: 14px 0 0;
  list-style: none;
}

@media (max-width: 1100px) {
  .step-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .workspace-grid {
    grid-template-columns: 1fr;
  }
}
</style>
