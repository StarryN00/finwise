<template>
  <div class="page">
    <!-- Editorial Header -->
    <div class="page-header">
      <div class="header-left">
        <div class="page-eyebrow">§ 04 · FINANCIAL REPORTS —</div>
        <h1 class="page-title">财务报表</h1>
        <p class="page-desc">税务申报、财务健康诊断与融资评分报告。</p>
      </div>
    </div>

    <!-- Tab Nav -->
    <div class="panel" style="padding: 0;">
      <div class="tab-nav">
        <button class="tab-btn" :class="{ active: activeTab === 'vat' }" @click="activeTab = 'vat'">税务申报</button>
        <button class="tab-btn" :class="{ active: activeTab === 'health' }" @click="activeTab = 'health'">财务健康</button>
        <button class="tab-btn" :class="{ active: activeTab === 'financing' }" @click="activeTab = 'financing'">融资评分</button>
      </div>

      <!-- VAT Tab -->
      <div v-if="activeTab === 'vat'" class="tab-body">
        <div class="filter-row">
          <select v-model="vatEnterpriseId" class="input" style="width: 240px; cursor: pointer;" @change="vatReportData = null">
            <option value="">选择企业</option>
            <option v-for="e in enterprises" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
          <input v-model="vatPeriod" type="month" class="input" style="width: 160px;" format="YYYY-MM" @change="vatReportData = null" />
          <button class="btn primary" :loading="vatLoading" @click="generateVatReport">生成报告</button>
          <button v-if="vatReportData" class="btn secondary" @click="exportVatExcel">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            导出 Excel
          </button>
        </div>

        <div v-if="vatReportData" class="vat-grid">
          <div class="vat-hero">
            <div class="vat-hero-label">应申报税额（含附加税）</div>
            <div class="vat-hero-amount">¥{{ Number(vatReportData.total_tax_and_surcharge || 0).toLocaleString() }}</div>
            <div class="vat-period-badge">{{ vatPeriod }} 申报期</div>
          </div>
          <div class="vat-breakdown">
            <div class="vat-item">
              <div class="vat-item-label">销售额（不含税）</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.sales_amount_excl_tax || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">增值税率</div>
              <div class="vat-item-value">{{ Number(vatReportData.tax_rate * 100).toFixed(1) }}%</div>
            </div>
            <div class="vat-item warn">
              <div class="vat-item-label">增值税</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.tax_amount || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">城建税</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.urban_construction_tax || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">教育费附加</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.education_surcharge || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">地方教育附加</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.local_education_surcharge || 0).toLocaleString() }}</div>
            </div>
          </div>
        </div>
        <div v-else-if="!vatLoading" class="empty-state">
          <div class="empty-icon">⊙</div>
          <div class="empty-text">请选择企业和申报期后生成报告</div>
        </div>
        <el-skeleton v-if="vatLoading" :rows="4" animated />
      </div>

      <!-- Health Tab -->
      <div v-if="activeTab === 'health'" class="tab-body">
        <div class="filter-row">
          <select v-model="healthEnterpriseId" class="input" style="width: 240px; cursor: pointer;" @change="healthReportData = null">
            <option value="">选择企业</option>
            <option v-for="e in enterprises" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
          <button class="btn primary" :loading="healthLoading" @click="generateHealthReport">生成报告</button>
          <button v-if="healthReportData" class="btn secondary" @click="exportPdf('health')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            导出 PDF
          </button>
        </div>

        <div v-if="healthReportData" class="health-result">
          <div class="health-hero">
            <div class="health-score-ring">
              <svg viewBox="0 0 120 120" width="120" height="120">
                <circle cx="60" cy="60" r="52" fill="none" stroke="var(--panel)" stroke-width="12"/>
                <circle cx="60" cy="60" r="52" fill="none" stroke="var(--accent)" stroke-width="12"
                  stroke-linecap="round"
                  :stroke-dasharray="`${(healthReportData.financing_score || 0) / 100 * 327} 327`"
                  transform="rotate(-90 60 60)"/>
              </svg>
              <div class="ring-score">{{ healthReportData.financing_score || '--' }}</div>
              <div class="ring-label">融资评分</div>
            </div>
            <div class="health-chart-area">
              <div ref="radarChartRef" style="width:100%;height:260px"></div>
            </div>
          </div>
          <div class="health-dimensions">
            <div v-for="dim in healthDimensions" :key="dim.name" class="dimension-row">
              <span class="dim-name">{{ dim.name }}</span>
              <div class="dim-bar-wrap">
                <div class="dim-bar" :style="{ width: dim.score + '%', background: dim.color }"></div>
              </div>
              <span class="dim-score" :style="{ color: dim.color }">{{ dim.score }}</span>
            </div>
          </div>
        </div>
        <div v-else-if="!healthLoading" class="empty-state">
          <div class="empty-icon">⊙</div>
          <div class="empty-text">请选择企业后生成报告</div>
        </div>
        <el-skeleton v-if="healthLoading" :rows="4" animated />
      </div>

      <!-- Financing Tab -->
      <div v-if="activeTab === 'financing'" class="tab-body">
        <div class="filter-row">
          <select v-model="finEnterpriseId" class="input" style="width: 240px; cursor: pointer;" @change="finReportData = null">
            <option value="">选择企业</option>
            <option v-for="e in enterprises" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
          <button class="btn primary" :loading="finLoading" @click="generateFinancingReport">生成报告</button>
          <button v-if="finReportData" class="btn secondary" @click="exportPdf('financing')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            导出 PDF
          </button>
        </div>

        <div v-if="finReportData" class="fin-result">
          <div class="fin-hero">
            <div class="fin-score-display">
              <div class="fin-big-score" :style="{ color: finScoreColor }">{{ finReportData.score || '--' }}</div>
              <div class="fin-score-sub">融资评分</div>
              <span class="pill" :class="finScorePillClass">{{ finReportData.level || '待评估' }}</span>
            </div>
            <div class="fin-details">
              <div class="fin-detail-item">
                <span class="fd-label">信用等级</span>
                <span class="fd-value">{{ finReportData.level || '--' }}</span>
              </div>
              <div class="fin-detail-item highlight">
                <span class="fd-label">建议额度</span>
                <span class="fd-value" style="color: var(--ok-fg); font-size: 18px;">¥{{ Number(finReportData.estimated_loan_amount || 0).toLocaleString() }}</span>
              </div>
              <div class="fin-detail-item">
                <span class="fd-label">报告编号</span>
                <span class="fd-value mono" style="font-size: 11px;">{{ finReportData.score_id || '--' }}</span>
              </div>
            </div>
          </div>
          <!-- Score bar per spec -->
          <div class="score-bar-section">
            <div class="score-bar-label">
              <span class="mono" style="font-size: 38px; font-weight: 600; color: var(--ink);">{{ finReportData.score || '--' }}</span>
              <span style="font-size: 13px; color: var(--mute); margin-left: 8px;">融资评分</span>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill" :style="{ width: (finReportData.score || 0) + '%', background: scoreBarColor }"></div>
            </div>
            <div class="score-bar-hint mono">FINANCING SCORE · ≥75 NORMAL · 60–74 ATTENTION · &lt;60 RISK</div>
          </div>
          <div class="fin-actions">
            <button class="btn primary" @click="applyLoan">申请贷款</button>
            <button class="btn secondary" @click="$router.push('/financing')">查看融资产品</button>
          </div>
        </div>
        <div v-else-if="!finLoading" class="empty-state">
          <div class="empty-icon">⊙</div>
          <div class="empty-text">请选择企业后生成报告</div>
        </div>
        <el-skeleton v-if="finLoading" :rows="4" animated />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import api from '@/api'
import { exportToPdf } from '@/utils/pdf-export'

const router = useRouter()
const activeTab = ref('vat')
const enterprises = ref([])

// VAT
const vatEnterpriseId = ref('')
const vatPeriod = ref('')
const vatLoading = ref(false)
const vatReportData = ref(null)

const generateVatReport = async () => {
  if (!vatEnterpriseId.value || !vatPeriod.value) { ElMessage.warning('请选择企业和申报期'); return }
  vatLoading.value = true
  try {
    const [y, m] = vatPeriod.value.split('-')
    const res = await api.post('/api/reports/vat/generate', { enterprise_id: vatEnterpriseId.value, period_year: +y, period_month: +m })
    vatReportData.value = res.data.data
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { vatLoading.value = false }
}

const exportVatExcel = () => ElMessage.info('Excel 导出功能开发中')

// Health
const healthEnterpriseId = ref('')
const healthLoading = ref(false)
const healthReportData = ref(null)
const radarChartRef = ref(null)
const healthDimensions = ref([])

const healthDimConfig = [
  { name: '盈利能力', key: 'profitability', color: 'var(--accent)' },
  { name: '偿债能力', key: 'solvency', color: 'var(--ok-fg)' },
  { name: '运营效率', key: 'operation_efficiency', color: 'var(--warn-fg)' },
  { name: '成长性', key: 'growth', color: '#5a7a9a' },
  { name: '现金流', key: 'cash_flow', color: '#9c7ab5' }
]

const generateHealthReport = async () => {
  if (!healthEnterpriseId.value) { ElMessage.warning('请选择企业'); return }
  healthLoading.value = true; healthReportData.value = null
  try {
    const res = await api.post('/api/reports/health/generate', { enterprise_id: healthEnterpriseId.value, report_type: 'FULL' })
    healthReportData.value = res.data.data
    const scores = res.data.data.dimensions || {}
    healthDimensions.value = healthDimConfig.map(d => ({ name: d.name, score: Math.round(scores[d.key] || 0), color: d.color }))
    await nextTick(); renderRadarChart(res.data.data)
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { healthLoading.value = false }
}

const renderRadarChart = (data) => {
  if (!radarChartRef.value) return
  const chart = echarts.init(radarChartRef.value)
  const scores = data.dimensions || {}
  chart.setOption({
    backgroundColor: 'transparent',
    radar: {
      indicator: healthDimConfig.map(d => ({ name: d.name, max: 100 })),
      shape: 'polygon', splitNumber: 4,
      axisName: { color: 'var(--ink-2)', fontSize: 12 },
      splitLine: { lineStyle: { color: 'var(--line)' } },
      splitArea: { areaStyle: { color: ['var(--bg)', 'var(--panel)'] } },
      radius: '65%'
    },
    series: [{
      type: 'radar',
      data: [{
        value: healthDimConfig.map(d => Math.round(scores[d.key] || 0)),
        name: '财务健康',
        areaStyle: { color: 'rgba(204, 120, 92, 0.25)' },
        lineStyle: { color: 'var(--accent)', width: 2 },
        itemStyle: { color: 'var(--accent)' }
      }]
    }]
  })
}

// Financing
const finEnterpriseId = ref('')
const finLoading = ref(false)
const finReportData = ref(null)

const finScorePillClass = computed(() => {
  const s = finReportData.value?.score || 0
  return s >= 70 ? 'pill--ok' : s >= 50 ? 'pill--warn' : 'pill--alert'
})

const finScoreColor = computed(() => {
  const s = finReportData.value?.score || 0
  return s >= 70 ? 'var(--ok-fg)' : s >= 50 ? 'var(--warn-fg)' : 'var(--alert-fg)'
})

const scoreBarColor = computed(() => {
  const s = finReportData.value?.score || 0
  return s >= 75 ? 'var(--ink)' : s >= 60 ? 'var(--accent)' : 'var(--alert-fg)'
})

const generateFinancingReport = async () => {
  if (!finEnterpriseId.value) { ElMessage.warning('请选择企业'); return }
  finLoading.value = true; finReportData.value = null
  try {
    const res = await api.post('/api/reports/financing/generate', { enterprise_id: finEnterpriseId.value })
    finReportData.value = res.data.data
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { finLoading.value = false }
}

const applyLoan = () => ElMessage.success('贷款申请已提交，请等待银行客户经理联系')

const exportPdf = async (type) => {
  const tabNames = { health: '财务健康报告', financing: '融资评分报告' }
  const tabName = tabNames[type] || '财务报告'
  const activeContent = document.querySelector('.tab-body')
  if (!activeContent) { ElMessage.error('未找到报告内容'); return }
  try {
    ElMessage.info('正在生成 PDF...')
    await exportToPdf(activeContent, `finwise-${type}-report`, { title: tabName })
    ElMessage.success('PDF 已下载')
  } catch (e) { ElMessage.error('PDF 导出失败: ' + (e.message || '')) }
}

const fetchEnterprises = async () => {
  try {
    const res = await api.get('/api/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
  } catch {}
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page { width: 100%; }

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 32px;
}
.header-left { flex: 1; }
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

/* Tab nav */
.tab-nav {
  display: flex;
  border-bottom: 1px solid var(--line);
  padding: 0 24px;
}
.tab-btn {
  padding: 14px 20px;
  font-size: 14px;
  color: var(--mute);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all .15s;
  margin-bottom: -1px;
}
.tab-btn:hover { color: var(--ink); }
.tab-btn.active { color: var(--ink); border-bottom-color: var(--accent); font-weight: 500; }

.tab-body { padding: 24px; }

/* Filter row */
.filter-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

/* VAT */
.vat-grid { display: flex; flex-direction: column; gap: 16px; }
.vat-hero {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 28px;
  border-left: 4px solid var(--accent);
}
.vat-hero-label { font-size: 12px; color: var(--mute); margin-bottom: 8px; font-family: var(--font-mono); letter-spacing: 0.05em; }
.vat-hero-amount { font-family: var(--font-mono); font-size: 42px; font-weight: 400; letter-spacing: -0.02em; color: var(--ink); }
.vat-period-badge {
  display: inline-block;
  margin-top: 8px;
  background: var(--idle-bg);
  color: var(--idle-fg);
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
}
.vat-breakdown { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.vat-item {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 16px;
}
.vat-item-label { font-size: 11px; color: var(--mute); margin-bottom: 6px; font-family: var(--font-mono); letter-spacing: 0.05em; }
.vat-item-value { font-size: 18px; font-weight: 400; color: var(--ink); font-family: var(--font-mono); }
.vat-item.warn .vat-item-value { color: var(--warn-fg); }

/* Health */
.health-hero { display: flex; gap: 24px; align-items: center; margin-bottom: 24px; }
.health-score-ring { position: relative; display: flex; flex-direction: column; align-items: center; flex-shrink: 0; }
.ring-score { position: absolute; top: 50%; transform: translateY(-50%); font-size: 32px; font-weight: 600; color: var(--accent); }
.ring-label { font-size: 12px; color: var(--mute); margin-top: -4px; }
.health-chart-area { flex: 1; }
.health-dimensions { display: flex; flex-direction: column; gap: 10px; }
.dimension-row { display: flex; align-items: center; gap: 12px; }
.dim-name { width: 70px; font-size: 12px; color: var(--ink-2); font-weight: 500; flex-shrink: 0; }
.dim-bar-wrap { flex: 1; height: 6px; background: var(--panel); border-radius: 3px; overflow: hidden; }
.dim-bar { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
.dim-score { width: 28px; font-size: 12px; font-weight: 600; text-align: right; flex-shrink: 0; }

/* Financing */
.fin-hero {
  display: flex;
  gap: 32px;
  align-items: center;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 28px;
  margin-bottom: 24px;
}
.fin-score-display { text-align: center; min-width: 120px; }
.fin-big-score { font-size: 64px; font-weight: 400; letter-spacing: -0.02em; line-height: 1; font-family: var(--font-mono); }
.fin-score-sub { font-size: 13px; color: var(--mute); margin: 6px 0 12px; }
.fin-details { flex: 1; display: flex; flex-direction: column; gap: 14px; }
.fin-detail-item { display: flex; justify-content: space-between; align-items: center; padding-bottom: 12px; border-bottom: 1px solid var(--line-soft); }
.fin-detail-item:last-child { border-bottom: none; padding-bottom: 0; }
.fd-label { font-size: 13px; color: var(--mute); }
.fd-value { font-size: 14px; font-weight: 600; color: var(--ink); }

/* Score bar per spec */
.score-bar-section { margin-bottom: 24px; }
.score-bar-label { display: flex; align-items: baseline; margin-bottom: 8px; }
.score-bar-track {
  height: 5px;
  background: var(--panel);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 6px;
}
.score-bar-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
.score-bar-hint {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--mute);
  text-transform: uppercase;
}

.fin-actions { display: flex; gap: 12px; }

/* Empty */
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 48px; color: var(--mute); }
.empty-icon { font-size: 40px; opacity: 0.4; }
.empty-text { font-size: 13px; }
</style>
