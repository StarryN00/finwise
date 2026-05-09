<template>
  <div class="dashboard">
    <!-- Editorial Header -->
    <div class="page-header">
      <div class="header-left">
        <div class="page-eyebrow">§ 01 · WORKSPACE —</div>
        <h1 class="page-title">数据总览</h1>
        <p class="page-desc">实时监控全服务企业的财税运营状态与待办事项。</p>
      </div>
    </div>

    <!-- KPI Row -->
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-eyebrow">SERVICE · ENTERPRISES · REALTIME</div>
        <div class="kpi-number">12</div>
        <div class="kpi-sub">服务企业数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-eyebrow">INVOICE · THIS MONTH · REALTIME</div>
        <div class="kpi-number">256</div>
        <div class="kpi-sub">本月发票数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-eyebrow">PENDING · TAX FILING · REALTIME</div>
        <div class="kpi-number">18</div>
        <div class="kpi-sub">待申报任务</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-eyebrow">FINANCING · DEMAND · REALTIME</div>
        <div class="kpi-number">5</div>
        <div class="kpi-sub">融资需求</div>
      </div>
    </div>

    <!-- Content Row -->
    <div class="content-row">
      <!-- Recent Activity -->
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-eyebrow mono">RECENT · ACTIVITY</div>
            <div class="panel-title">最近操作记录</div>
          </div>
        </div>
        <div class="activity-list">
          <div class="activity-item">
            <span class="pill pill--ok">已完成</span>
            <span class="activity-desc">完成 xxx 公司的增值税申报</span>
            <span class="activity-time mono">2026-05-07 16:30</span>
          </div>
          <div class="activity-item">
            <span class="pill pill--info">已导入</span>
            <span class="activity-desc">导入银行对账单 23 条</span>
            <span class="activity-time mono">2026-05-07 14:20</span>
          </div>
          <div class="activity-item">
            <span class="pill pill--ok">已完成</span>
            <span class="activity-desc">生成 xxx 公司财务分析报告</span>
            <span class="activity-time mono">2026-05-07 10:15</span>
          </div>
        </div>
      </div>

      <!-- Quick Actions -->
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-eyebrow mono">QUICK · ACTIONS</div>
            <div class="panel-title">快捷操作</div>
          </div>
          <div class="seg">
            <button :class="{ on: actionView === 'list' }" @click="actionView = 'list'">列表</button>
            <button :class="{ on: actionView === 'grid' }" @click="actionView = 'grid'">网格</button>
          </div>
        </div>
        <div class="quick-actions">
          <button class="btn primary" @click="$router.push('/invoices')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            导入发票
          </button>
          <button class="btn secondary" @click="$router.push('/reports')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            发起申报
          </button>
          <button class="btn secondary" @click="$router.push('/reports')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            生成报告
          </button>
          <button class="btn secondary" @click="$router.push('/enterprises')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            添加企业
          </button>
        </div>
      </div>
    </div>

    <!-- Charts Row -->
    <div class="charts-row">
      <div class="panel chart-panel">
        <div class="panel-header">
          <div>
            <div class="panel-eyebrow mono">INVOICE · TREND · 30D</div>
            <div class="panel-title">近30天发票趋势</div>
          </div>
          <div class="seg small">
            <button :class="{ on: invoiceView === 'month' }" @click="invoiceView = 'month'">月</button>
            <button :class="{ on: invoiceView === 'week' }" @click="invoiceView = 'week'">周</button>
          </div>
        </div>
        <div ref="invoiceChartRef" style="width: 100%; height: 220px;"></div>
      </div>

      <div class="panel chart-panel">
        <div class="panel-header">
          <div>
            <div class="panel-eyebrow mono">TAX · BREAKDOWN</div>
            <div class="panel-title">税务构成</div>
          </div>
        </div>
        <div ref="taxChartRef" style="width: 100%; height: 220px;"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const actionView = ref('list')
const invoiceChartRef = ref(null)
const taxChartRef = ref(null)
const invoiceView = ref('month')

onMounted(async () => {
  await nextTick()
  renderInvoiceChart()
  renderTaxChart()
})

const renderInvoiceChart = () => {
  if (!invoiceChartRef.value) return
  const chart = echarts.init(invoiceChartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: ['1日','5日','10日','15日','20日','25日','30日'], axisLine: { lineStyle: { color: '#d4cfc3' } }, axisLabel: { color: '#8a8474', fontSize: 11 } },
    yAxis: { type: 'value', axisLine: { show: false }, splitLine: { lineStyle: { color: 'rgba(41,38,27,0.06)' } }, axisLabel: { color: '#8a8474', fontSize: 11 } },
    series: [
      { name: '销项', type: 'bar', data: [12, 25, 18, 32, 28, 45, 38], smooth: false, barWidth: 12, barRadius: [3, 3, 0, 0], itemStyle: { color: '#c07055' }, label: { show: false } },
      { name: '进项', type: 'bar', data: [8, 15, 22, 18, 35, 28, 42], smooth: false, barWidth: 12, barRadius: [3, 3, 0, 0], itemStyle: { color: '#29261b' }, label: { show: false } }
    ]
  })
}

const renderTaxChart = () => {
  if (!taxChartRef.value) return
  const chart = echarts.init(taxChartRef.value)
  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: { show: false },
    grid: { left: 8, right: 8, top: 8, bottom: 8 },
    series: [{
      type: 'pie',
      radius: ['50%', '75%'],
      center: ['50%', '50%'],
      label: { show: true, formatter: '{b}', fontSize: 12, color: 'var(--ink-2)' },
      data: [
        { value: 45, name: '增值税', itemStyle: { color: 'var(--accent)' } },
        { value: 28, name: '企业所得税', itemStyle: { color: 'var(--ok-fg)' } },
        { value: 18, name: '个人所得税', itemStyle: { color: 'var(--warn-fg)' } },
        { value: 9, name: '其他', itemStyle: { color: 'var(--mute)' } }
      ]
    }]
  })
}
</script>

<style scoped>
.dashboard { width: 100%; }

.page-header {
  background: #e6dcd0;
  margin: -24px -24px 24px;
  padding: 28px 24px;
  border-radius: 0;
}
.page-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  color: #8a6a5a;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.page-title {
  font-size: 48px;
  font-weight: 600;
  letter-spacing: -0.022em;
  color: var(--ink);
  margin-bottom: 8px;
  line-height: 1.1;
}
.page-desc {
  font-size: 13.5px;
  color: var(--mute);
  line-height: 1.7;
}

/* KPI row */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  padding: 24px;
  background: #f1ebdd;
  border: none;
  border-radius: 14px;
}

.kpi-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
  margin-bottom: 12px;
}
.kpi-number {
  font-family: var(--font-mono);
  font-size: 64px;
  font-weight: 400;
  letter-spacing: -0.02em;
  color: var(--ink);
  line-height: 1;
  margin-bottom: 8px;
}
.kpi-sub {
  font-size: 13px;
  color: var(--ink-2);
}

/* Panel eyebrow + title */
.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}
.panel-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
  margin-bottom: 6px;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}

/* Segmented tab */
.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 999px;
  overflow: hidden;
  flex-shrink: 0;
}
.seg button {
  padding: 0 14px;
  height: 40px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--mute);
}
.seg button.on { background: var(--ink); color: var(--bg); }
.seg.small button {
  padding: 0 12px;
  height: 32px;
  font-size: 12px;
}

/* Activity list */
.activity-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.activity-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line-soft);
}
.activity-item:last-child { border-bottom: none; }
.activity-desc {
  flex: 1;
  font-size: 13.5px;
  color: var(--ink);
}
.activity-time {
  font-size: 11px;
  color: var(--mute);
  letter-spacing: 0.05em;
  flex-shrink: 0;
}

/* Pill */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px 4px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  flex-shrink: 0;
}
.pill::before {
  content: "";
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex: 0 0 5px;
}
.pill--ok    { background: rgba(16,128,67,.08);   color: #0f7a3f; }
.pill--warn  { background: rgba(204,120,92,.14);  color: #b86749; }
.pill--alert { background: rgba(211,47,47,.08);   color: #c1372d; }
.pill--info  { background: rgba(204,120,92,.10);  color: #cc785c; }
.pill--idle  { background: rgba(41,38,27,.05);    color: #8a8474; }

/* Quick actions */
.quick-actions {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.quick-actions .btn {
  height: 40px;
  padding: 0 18px;
  font-size: 13px;
  white-space: nowrap;
}

/* Charts row */
.charts-row {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 16px;
  margin-top: 16px;
}
.chart-panel {
  background: #ede7d9;
  border: none;
  border-radius: 14px;
}
.chart-panel .panel-header {
  margin-bottom: 16px;
}
</style>
