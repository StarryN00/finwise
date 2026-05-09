<template>
  <div class="dashboard">
    <section class="digest-shell">
      <!-- Editorial Header -->
      <div class="page-header">
        <div class="header-left">
          <div class="page-eyebrow">§ 01 · MONTHLY DIGEST</div>
          <h1 class="page-title">财务月览</h1>
          <p class="page-desc">本月企业税务与健康状况摘要，所有数据更新至昨晚 23:59，由系统自动核算并人工复核。</p>
        </div>
        <div class="header-right">
          <div class="publish-card">
            <div class="publish-label mono">PUBLISHED ON</div>
            <div class="publish-date mono">2026 - 05 - 08</div>
          </div>
          <button class="btn ghost export-btn">导出 PDF 月刊</button>
        </div>
      </div>

      <!-- KPI Row -->
      <div class="kpi-row">
        <div v-for="(item, index) in kpis" :key="item.label" class="kpi-card">
          <div class="kpi-topline">
            <div class="kpi-eyebrow">{{ item.scope }}</div>
            <span class="pill" :class="item.pillClass">{{ item.badge }}</span>
          </div>
          <div class="kpi-number">
            {{ item.value }}<span v-if="item.unit" class="kpi-unit">{{ item.unit }}</span>
          </div>
          <div class="kpi-sub">{{ item.label }}</div>
          <div class="kpi-bottom">
            <span class="kpi-trend mono" :class="{ down: item.trendDirection === 'down' }">
              {{ item.trend }}
            </span>
            <div :ref="el => setSparklineRef(el, index)" class="sparkline"></div>
          </div>
        </div>
      </div>

      <!-- Charts Row -->
      <div class="charts-row">
        <div class="panel chart-panel industry-panel">
          <div class="panel-header">
            <div>
              <div class="panel-title">行业分布概览</div>
              <div class="panel-eyebrow mono">FIG. 01 · BY SECTOR · N = 1,248</div>
            </div>
            <div class="seg small">
              <button :class="{ on: industryView === 'count' }" @click="industryView = 'count'">数量</button>
              <button :class="{ on: industryView === 'amount' }" @click="industryView = 'amount'">金额</button>
              <button :class="{ on: industryView === 'yoy' }" @click="industryView = 'yoy'">同比</button>
            </div>
          </div>
          <div ref="industryChartRef" class="industry-chart"></div>
          <div class="panel-footer mono">
            <span>SOURCE · INTERNAL LEDGER</span>
            <span>UPDATED · 05.08 09:14</span>
          </div>
        </div>

        <div class="panel chart-panel active-panel">
          <div class="panel-header">
            <div>
              <div class="panel-title">企业活跃状态</div>
              <div class="panel-eyebrow mono">FIG. 02 · ACTIVE / DORMANT</div>
            </div>
            <div class="seg small">
              <button :class="{ on: activeView === 'month' }" @click="activeView = 'month'">本月</button>
              <button :class="{ on: activeView === 'quarter' }" @click="activeView = 'quarter'">季度</button>
            </div>
          </div>
          <div class="donut-content">
            <div class="donut-wrap">
              <div ref="activeChartRef" class="active-chart"></div>
              <div class="donut-center">
                <strong>74%</strong>
                <span class="mono">ACTIVE</span>
              </div>
            </div>
            <div class="active-legend">
              <div v-for="item in activeStats" :key="item.name" class="legend-row">
                <span class="legend-dot" :style="{ background: item.color }"></span>
                <span class="legend-name">{{ item.name }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.rate }}</small>
              </div>
            </div>
          </div>
          <div class="panel-footer mono">
            <span>SAMPLE · 1,248</span>
            <span>ERROR · 0.6% · 需重点回访</span>
          </div>
        </div>
      </div>

      <footer class="digest-footer">
        <span class="footer-brand mono">智税月览 · MONTHLY DIGEST</span>
        <span class="page-index mono">— 01/04 —</span>
        <a href="#" class="next-link">下一页 →</a>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'

const industryChartRef = ref(null)
const activeChartRef = ref(null)
const industryView = ref('count')
const activeView = ref('month')
const sparklineRefs = []
const charts = []

const kpis = [
  {
    scope: '总企业数 / TOTAL',
    badge: 'REALTIME',
    pillClass: 'pill--idle',
    value: '1,248',
    label: '服务企业总数',
    trend: '↑ 3.2% · +300',
    trendDirection: 'up',
    data: [22, 24, 23, 27, 29, 28, 32]
  },
  {
    scope: '待办行业 / QUEUE',
    badge: '需关注',
    pillClass: 'pill--warn',
    value: '56',
    label: '待申报企业',
    trend: '↓ 8 · 较上月',
    trendDirection: 'down',
    data: [31, 29, 30, 26, 24, 25, 22]
  },
  {
    scope: '已出报告 / PUBLISHED',
    badge: '+12%',
    pillClass: 'pill--ok',
    value: '892',
    label: '已发布月报',
    trend: '↑ 同比 · YoY',
    trendDirection: 'up',
    data: [18, 20, 21, 24, 27, 30, 33]
  },
  {
    scope: '健康均值 / AVG',
    badge: '月度',
    pillClass: 'pill--idle',
    value: '85.4',
    unit: '/ 100',
    label: '企业健康评分',
    trend: '↑ 2.1 较上月',
    trendDirection: 'up',
    data: [78, 80, 79, 82, 81, 84, 85.4]
  }
]

const activeStats = [
  { name: '活跃企业', value: 923, rate: '74%', color: 'var(--ink)' },
  { name: '异常企业', value: 186, rate: '14%', color: 'var(--accent)' },
  { name: '休眠企业', value: 139, rate: '11%', color: 'var(--line-strong)' }
]

const setSparklineRef = (el, index) => {
  if (el) sparklineRefs[index] = el
}

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

onMounted(async () => {
  await nextTick()
  renderSparklines()
  renderIndustryChart()
  renderActiveChart()
  window.addEventListener('resize', resizeCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeCharts)
  charts.forEach(chart => chart.dispose())
})

watch(industryView, () => renderIndustryChart())
watch(activeView, () => renderActiveChart())

const rememberChart = (chart) => {
  charts.push(chart)
  return chart
}

const resizeCharts = () => {
  charts.forEach(chart => chart.resize())
}

const renderSparklines = () => {
  sparklineRefs.forEach((el, index) => {
    if (!el) return
    const chart = rememberChart(echarts.init(el))
    chart.setOption({
      animation: false,
      grid: { left: 2, right: 2, top: 6, bottom: 6 },
      xAxis: { type: 'category', show: false, boundaryGap: false, data: kpis[index].data.map((_, i) => i) },
      yAxis: { type: 'value', show: false, min: 'dataMin', max: 'dataMax' },
      series: [{
        type: 'line',
        data: kpis[index].data,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.2, color: kpis[index].trendDirection === 'down' ? cssVar('--accent') : cssVar('--ink') },
        areaStyle: { opacity: 0 }
      }]
    })
  })
}

const renderIndustryChart = () => {
  if (!industryChartRef.value) return
  const existing = echarts.getInstanceByDom(industryChartRef.value)
  if (existing) existing.dispose()

  const labels = ['制造业', '科技', '零售', '服务业', '建筑', '金融', '其他']
  const values = [328, 276, 182, 142, 118, 82, 120]
  const max = 360
  const chart = rememberChart(echarts.init(industryChartRef.value))
  chart.setOption({
    animation: false,
    grid: { left: 74, right: 50, top: 4, bottom: 4 },
    xAxis: { type: 'value', show: false, max },
    yAxis: {
      type: 'category',
      inverse: true,
      data: labels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: cssVar('--ink'), fontSize: 13, margin: 14 }
    },
    series: [
      {
        type: 'bar',
        data: labels.map(() => max),
        barWidth: 10,
        barGap: '-100%',
        silent: true,
        itemStyle: { color: cssVar('--line-soft') }
      },
      {
        type: 'bar',
        data: values.map((value, index) => ({
          value,
          itemStyle: { color: labels[index] === '零售' ? cssVar('--accent') : cssVar('--ink') }
        })),
        barWidth: 10,
        label: {
          show: true,
          position: 'right',
          formatter: '{c}',
          color: cssVar('--ink'),
          fontSize: 16,
          distance: 20
        },
        itemStyle: { borderRadius: 0 }
      }
    ]
  })
}

const renderActiveChart = () => {
  if (!activeChartRef.value) return
  const existing = echarts.getInstanceByDom(activeChartRef.value)
  if (existing) existing.dispose()

  const chart = rememberChart(echarts.init(activeChartRef.value))
  chart.setOption({
    animation: false,
    tooltip: { show: false },
    series: [{
      type: 'pie',
      radius: ['70%', '84%'],
      center: ['50%', '50%'],
      startAngle: 110,
      avoidLabelOverlap: true,
      label: { show: false },
      labelLine: { show: false },
      data: [
        { value: 74, name: '活跃企业', itemStyle: { color: cssVar('--ink') } },
        { value: 14, name: '异常企业', itemStyle: { color: cssVar('--accent') } },
        { value: 12, name: '休眠企业', itemStyle: { color: cssVar('--line-strong') } }
      ]
    }]
  })
}
</script>

<style scoped>
.dashboard {
  width: 100%;
}

.digest-shell {
  background: var(--bg);
  border: 1px solid var(--line);
  box-shadow: 0 18px 48px rgba(41, 38, 27, 0.08);
}

.page-header {
  min-height: 164px;
  padding: 28px 40px 24px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
}

.header-left {
  min-width: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.page-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 8px;
}

.page-title {
  font-size: 48px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--ink);
  margin-bottom: 8px;
  line-height: 1.08;
}

.page-title::first-letter {
  color: var(--ink);
}

.page-desc {
  max-width: 620px;
  font-size: 13px;
  color: var(--mute);
  line-height: 1.75;
}

.publish-card {
  min-width: 150px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(241, 235, 221, 0.44);
}

.publish-label {
  font-size: 9px;
  letter-spacing: 0.2em;
  color: var(--mute);
  margin-bottom: 4px;
}

.publish-date {
  font-size: 16px;
  letter-spacing: 0.06em;
  color: var(--ink);
}

.export-btn {
  border: 1px solid var(--ink);
  text-decoration: none;
  height: 42px;
  padding: 0 18px;
}

/* KPI row */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}

.kpi-card {
  min-height: 152px;
  padding: 22px 28px 18px;
  background: transparent;
  border: none;
  border-radius: 0;
  border-right: 1px solid var(--line-strong);
}

.kpi-card:last-child {
  border-right: none;
}

.kpi-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.kpi-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
}

.kpi-card .pill {
  padding: 3px 8px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  white-space: nowrap;
}

.kpi-card .pill::before {
  display: none;
}

.kpi-number {
  font-family: var(--font-mono);
  font-size: clamp(42px, 4.8vw, 62px);
  font-weight: 400;
  letter-spacing: 0;
  color: var(--ink);
  line-height: 0.95;
  margin-bottom: 10px;
}

.kpi-unit {
  margin-left: 6px;
  font-family: var(--font-sans);
  font-size: 12px;
  color: var(--mute);
}

.kpi-sub {
  font-size: 13px;
  color: var(--ink-2);
}

.kpi-bottom {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  margin-top: 12px;
}

.kpi-trend {
  font-size: 11px;
  color: var(--ok-fg);
  white-space: nowrap;
}

.kpi-trend.down {
  color: var(--accent);
}

.sparkline {
  width: 78px;
  height: 28px;
  flex-shrink: 0;
}

/* Panel eyebrow + title */
.charts-row {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 0;
  padding: 22px 38px 16px;
}

.panel {
  min-width: 0;
  padding: 22px 22px 16px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.chart-panel {
  min-height: 318px;
}

.industry-panel {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
  padding-right: 18px;
}

.active-panel {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  border-left: none;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 4px;
}

.panel-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
}

.industry-chart {
  width: 100%;
  height: 220px;
}

.donut-content {
  min-height: 220px;
  display: grid;
  grid-template-columns: minmax(130px, 1fr) minmax(140px, 1fr);
  align-items: center;
  gap: 14px;
}

.donut-wrap {
  position: relative;
  width: 176px;
  height: 176px;
  max-width: 100%;
  justify-self: center;
}

.active-chart {
  width: 100%;
  height: 100%;
}

.donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.donut-center strong {
  font-family: var(--font-mono);
  font-size: 34px;
  font-weight: 400;
  line-height: 1;
  color: var(--ink);
}

.donut-center span {
  margin-top: 10px;
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--accent);
}

.active-legend {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.legend-row {
  display: grid;
  grid-template-columns: 8px minmax(58px, 1fr) auto auto;
  align-items: baseline;
  gap: 10px;
  color: var(--ink);
}

.legend-dot {
  width: 7px;
  height: 7px;
  margin-top: 4px;
}

.legend-name {
  font-size: 13px;
  color: var(--ink-2);
}

.legend-row strong {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 400;
}

.legend-row small {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--mute);
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  margin-top: 10px;
  font-size: 9px;
  letter-spacing: 0.18em;
  color: var(--mute);
}

/* Segmented tab */
.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 0;
  overflow: hidden;
  flex-shrink: 0;
}

.seg button {
  padding: 0 14px;
  height: 34px;
  background: transparent;
  border: none;
  border-right: 1px solid var(--line);
  cursor: pointer;
  font-size: 12px;
  color: var(--mute);
}

.seg button:last-child {
  border-right: none;
}

.seg button.on {
  background: var(--ink);
  color: var(--bg);
}

.seg.small button {
  padding: 0 12px;
  height: 30px;
  font-size: 12px;
}

.digest-footer {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 38px 18px;
  color: var(--mute);
  font-size: 11px;
}

.footer-brand {
  letter-spacing: 0.16em;
}

.page-index {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  color: var(--ink);
  letter-spacing: 0.08em;
}

.next-link {
  color: var(--mute);
  text-decoration: none;
}

.next-link:hover {
  color: var(--accent);
}

@media (max-width: 1200px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .kpi-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .kpi-card:nth-child(2) {
    border-right: none;
  }

  .kpi-card:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line-strong);
  }

  .charts-row {
    grid-template-columns: 1fr;
  }

  .industry-panel,
  .active-panel {
    border-radius: 8px;
  }

  .active-panel {
    border-left: 1px solid var(--line);
    border-top: none;
  }
}

@media (max-width: 760px) {
  .digest-shell {
    margin: -8px;
  }

  .page-header,
  .charts-row,
  .digest-footer {
    padding-left: 18px;
    padding-right: 18px;
  }

  .header-right {
    width: 100%;
    justify-content: space-between;
  }

  .page-title {
    font-size: 40px;
  }

  .kpi-row {
    grid-template-columns: 1fr;
  }

  .kpi-card {
    border-right: none;
    border-bottom: 1px solid var(--line-strong);
  }

  .kpi-card:last-child {
    border-bottom: none;
  }

  .donut-content {
    grid-template-columns: 1fr;
  }

  .panel-header {
    flex-direction: column;
  }

  .digest-footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .page-index {
    position: static;
    transform: none;
  }
}
</style>
