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
        <button class="tab-btn" :class="{ active: activeTab === 'monthly' }" @click="activeTab = 'monthly'">月度报告</button>
        <button class="tab-btn" :class="{ active: activeTab === 'vat' }" @click="activeTab = 'vat'">税务申报</button>
        <button class="tab-btn" :class="{ active: activeTab === 'health' }" @click="activeTab = 'health'">财务健康</button>
        <button class="tab-btn" :class="{ active: activeTab === 'financing' }" @click="activeTab = 'financing'">融资评分</button>
      </div>

      <!-- Monthly Tab -->
      <div v-if="activeTab === 'monthly'" class="tab-body">
        <div class="filter-row">
          <select v-model="monthlyEnterpriseId" class="input" style="width: 240px; cursor: pointer;" @change="monthlyReportData = null">
            <option value="">选择企业</option>
            <option v-for="e in enterprises" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
          <input v-model="monthlyPeriod" type="month" class="input" style="width: 160px;" @change="monthlyReportData = null" />
          <button class="btn primary" :disabled="monthlyLoading" @click="generateMonthlyReport">生成月报</button>
          <button v-if="monthlyReportData" class="btn secondary" @click="exportMonthlyCsv">导出 CSV</button>
        </div>

        <div v-if="monthlyReportData" class="monthly-grid">
          <div class="monthly-hero">
            <div class="monthly-label">月度财务评分</div>
            <div class="monthly-score">{{ monthlyReportData.overall_score }}</div>
            <span class="pill" :class="monthlyScorePillClass">{{ monthlyReportData.overall_grade }}</span>
          </div>
          <div class="monthly-cards">
            <div class="monthly-card">
              <span>现金流入</span>
              <strong>¥{{ Number(monthlyReportData.cash_inflow || 0).toLocaleString() }}</strong>
            </div>
            <div class="monthly-card">
              <span>现金流出</span>
              <strong>¥{{ Number(monthlyReportData.cash_outflow || 0).toLocaleString() }}</strong>
            </div>
            <div class="monthly-card">
              <span>净现金流</span>
              <strong>¥{{ Number(monthlyReportData.net_cash_flow || 0).toLocaleString() }}</strong>
            </div>
            <div class="monthly-card">
              <span>预计税费</span>
              <strong>¥{{ Number(monthlyReportData.total_tax || 0).toLocaleString() }}</strong>
            </div>
            <div class="monthly-card">
              <span>流水笔数</span>
              <strong>{{ monthlyReportData.transaction_count || 0 }}</strong>
            </div>
            <div class="monthly-card">
              <span>发票张数</span>
              <strong>{{ monthlyReportData.invoice_count || 0 }}</strong>
            </div>
          </div>
        </div>
        <div v-if="monthlyReportData && monthlyReportData.risk_alerts?.length" class="risk-list">
          <div v-for="item in monthlyReportData.risk_alerts" :key="item" class="risk-item">{{ item }}</div>
        </div>
        <div v-else-if="!monthlyLoading" class="empty-state">
          <div class="empty-icon">⊙</div>
          <div class="empty-text">请选择企业和月份后生成月度财务报告</div>
        </div>
        <el-skeleton v-if="monthlyLoading" :rows="4" animated />
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
              <div class="vat-item-value">{{ vatRateLabel }}</div>
            </div>
            <div class="vat-item warn">
              <div class="vat-item-label">增值税</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.tax_amount || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">城建税</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.surcharge_details?.urban_construction_tax || vatReportData.urban_construction_tax || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">教育费附加</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.surcharge_details?.education_surcharge || vatReportData.education_surcharge || 0).toLocaleString() }}</div>
            </div>
            <div class="vat-item">
              <div class="vat-item-label">地方教育附加</div>
              <div class="vat-item-value">¥{{ Number(vatReportData.surcharge_details?.local_education_surcharge || vatReportData.local_education_surcharge || 0).toLocaleString() }}</div>
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
          <input v-model="healthPeriod" type="month" class="input" style="width: 160px;" @change="healthReportData = null; dataCompleteness = null" />
          <button class="btn secondary" :disabled="!healthEnterpriseId || !healthPeriod" @click="checkDataCompleteness">检查数据</button>
          <button class="btn primary" :loading="healthLoading" @click="generateHealthReport">生成报告</button>
          <button v-if="healthReportData" class="btn secondary" @click="exportPdf('health')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            导出 PDF
          </button>
        </div>

        <div v-if="dataCompleteness" class="completeness-grid">
          <div class="completeness-card">
            <span>数据完整度</span>
            <strong>{{ dataCompleteness.completion_rate }}%</strong>
          </div>
          <div v-for="item in dataCompleteness.items" :key="item.key" class="data-check">
            <span class="pill" :class="item.status === 'READY' ? 'pill--ok' : 'pill--warn'">{{ item.status === 'READY' ? '已就绪' : '待补充' }}</span>
            <div>
              <strong>{{ item.label }}</strong>
              <p>{{ item.message }} · {{ item.count }} 条</p>
            </div>
          </div>
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
          <div class="metric-grid">
            <div class="monthly-card">
              <span>销项金额</span>
              <strong>¥{{ Number(healthReportData.key_metrics?.sales_amount || 0).toLocaleString() }}</strong>
            </div>
            <div class="monthly-card">
              <span>进项金额</span>
              <strong>¥{{ Number(healthReportData.key_metrics?.purchase_amount || 0).toLocaleString() }}</strong>
            </div>
            <div class="monthly-card">
              <span>净现金流</span>
              <strong>¥{{ Number(healthReportData.key_metrics?.net_cash_flow || 0).toLocaleString() }}</strong>
            </div>
          </div>
          <div v-if="healthReportData.sections?.length" class="report-sections">
            <div v-for="section in healthReportData.sections" :key="section.title" class="report-section">
              <h3>{{ section.title }}</h3>
              <p>{{ section.summary }}</p>
            </div>
          </div>
          <div v-if="healthReportData.missing_metrics?.length" class="risk-list">
            <div class="risk-item">数据不足项：{{ healthReportData.missing_metrics.join('、') }}</div>
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
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import api from '@/api'
import { exportToPdf } from '@/utils/pdf-export'

const router = useRouter()
const route = useRoute()
const activeTab = ref(route.query.tab || 'monthly')
const enterprises = ref([])

// Monthly
const monthlyEnterpriseId = ref('')
const monthlyPeriod = ref('')
const monthlyLoading = ref(false)
const monthlyReportData = ref(null)

const monthlyScorePillClass = computed(() => {
  const score = monthlyReportData.value?.overall_score || 0
  return score >= 75 ? 'pill--ok' : score >= 60 ? 'pill--warn' : 'pill--alert'
})

const generateMonthlyReport = async () => {
  if (!monthlyEnterpriseId.value || !monthlyPeriod.value) { ElMessage.warning('请选择企业和月份'); return }
  monthlyLoading.value = true
  try {
    const [y, m] = monthlyPeriod.value.split('-')
    const res = await api.post('/reports/monthly/generate', {
      enterprise_id: monthlyEnterpriseId.value,
      period_year: +y,
      period_month: +m
    })
    monthlyReportData.value = res.data.data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '生成月报失败')
  } finally {
    monthlyLoading.value = false
  }
}

const exportMonthlyCsv = () => {
  if (!monthlyReportData.value) return
  const ent = enterprises.value.find(e => e.id === monthlyEnterpriseId.value)
  const companyName = ent?.name || '未知企业'
  const d = monthlyReportData.value
  const rows = [
    ['指标', '数值'],
    ['现金流入', d.cash_inflow || 0],
    ['现金流出', d.cash_outflow || 0],
    ['净现金流', d.net_cash_flow || 0],
    ['销项金额', d.sales_amount || 0],
    ['进项金额', d.purchase_amount || 0],
    ['预计税费', d.total_tax || 0],
    ['月度评分', d.overall_score || 0],
    ['融资评分', d.financing_score || 0],
  ]
  const csv = rows.map(row => row.join(',')).join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `月度财务报告_${companyName}_${monthlyPeriod.value}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('CSV 导出成功')
}

// VAT
const vatEnterpriseId = ref('')
const vatPeriod = ref('')
const vatLoading = ref(false)
const vatReportData = ref(null)
const vatRateLabel = computed(() => {
  const raw = vatReportData.value?.tax_rate
  if (raw == null || raw === '') return '0.0%'
  if (typeof raw === 'string' && raw.includes('%')) return raw
  const num = Number(raw)
  return `${((Number.isFinite(num) ? num : 0) * 100).toFixed(1)}%`
})

const generateVatReport = async () => {
  if (!vatEnterpriseId.value || !vatPeriod.value) { ElMessage.warning('请选择企业和申报期'); return }
  vatLoading.value = true
  try {
    const [y, m] = vatPeriod.value.split('-')
    const res = await api.post('/reports/vat/generate', { enterprise_id: vatEnterpriseId.value, period_year: +y, period_month: +m })
    vatReportData.value = res.data.data
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { vatLoading.value = false }
}

const exportVatExcel = () => {
  if (!vatReportData.value) { ElMessage.warning('请先生成报告'); return }
  const ent = enterprises.value.find(e => e.id === vatEnterpriseId.value)
  const companyName = ent?.name || '未知企业'
  const d = vatReportData.value
  const headers = ['报告项', '金额']
  const rows = [
    ['销售额（不含税）', d.sales_amount_excl_tax || 0],
    ['增值税率', vatRateLabel.value],
    ['增值税', d.tax_amount || 0],
    ['城建税', d.surcharge_details?.urban_construction_tax || d.urban_construction_tax || 0],
    ['教育费附加', d.surcharge_details?.education_surcharge || d.education_surcharge || 0],
    ['地方教育附加', d.surcharge_details?.local_education_surcharge || d.local_education_surcharge || 0],
    ['应申报税额（含附加税）', d.total_tax_and_surcharge || 0],
  ]
  const csv = [headers.join(','), ...rows.map(r => `${r[0]},${r[1]}`)].join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `VAT_${companyName}_${vatPeriod.value}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('CSV 导出成功')
}

// Health
const healthEnterpriseId = ref('')
const healthPeriod = ref('')
const healthLoading = ref(false)
const healthReportData = ref(null)
const dataCompleteness = ref(null)
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
  if (!healthEnterpriseId.value || !healthPeriod.value) { ElMessage.warning('请选择企业和月份'); return }
  healthLoading.value = true; healthReportData.value = null
  try {
    const [y, m] = healthPeriod.value.split('-')
    const res = await api.post('/reports/health/generate', {
      enterprise_id: healthEnterpriseId.value,
      report_type: 'FULL',
      period_year: +y,
      period_month: +m
    })
    healthReportData.value = res.data.data
    dataCompleteness.value = res.data.data.data_completeness || dataCompleteness.value
    const scores = res.data.data.dimensions || {}
    healthDimensions.value = healthDimConfig.map(d => ({ name: d.name, score: Math.round(scores[d.key] || 0), color: d.color }))
    await nextTick(); renderRadarChart(res.data.data)
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { healthLoading.value = false }
}

const checkDataCompleteness = async () => {
  if (!healthEnterpriseId.value || !healthPeriod.value) { ElMessage.warning('请选择企业和月份'); return }
  const [y, m] = healthPeriod.value.split('-')
  try {
    const res = await api.get(`/reports/data-completeness/${healthEnterpriseId.value}`, {
      params: { period_year: +y, period_month: +m }
    })
    dataCompleteness.value = res.data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '数据检查失败')
  }
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
    const res = await api.post('/reports/financing/generate', { enterprise_id: finEnterpriseId.value })
    finReportData.value = res.data.data
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { finLoading.value = false }
}

const applyLoan = async () => {
  if (!finReportData.value) return
  const ent = enterprises.value.find(e => e.id === finEnterpriseId.value)
  const companyName = ent?.name || '未知企业'
  const d = finReportData.value
  try {
    await ElMessageBox.confirm(
      `企业名称：${companyName}\n融资评分：${d.score || '--'}\n建议额度：¥${Number(d.estimated_loan_amount || 0).toLocaleString()}\n匹配产品：${d.level || '待评估'}`,
      '贷款申请确认',
      { confirmButtonText: '确认提交', cancelButtonText: '取消', type: 'info' }
    )
    ElMessage.success('已提交，请等待银行经理联系')
  } catch {
    // user cancelled
  }
}

const exportPdf = async (type) => {
  const tabNames = { health: '财务健康报告', financing: '融资评分报告' }
  const tabName = tabNames[type] || '财务报告'
  let ent = null
  if (type === 'health') {
    ent = enterprises.value.find(e => e.id === healthEnterpriseId.value)
  } else if (type === 'financing') {
    ent = enterprises.value.find(e => e.id === finEnterpriseId.value)
  }
  const activeContent = document.querySelector('.tab-body')
  if (!activeContent) { ElMessage.error('未找到报告内容'); return }
  try {
    ElMessage.info('正在生成 PDF...')
    await exportToPdf(activeContent, `finwise-${type}-report`, { title: tabName, companyName: ent?.name || '' })
    ElMessage.success('PDF 已下载')
  } catch (e) { ElMessage.error('PDF 导出失败: ' + (e.message || '')) }
}

const fetchEnterprises = async () => {
  try {
    const res = await api.get('/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
    if (route.query.enterprise_id) {
      const enterpriseId = route.query.enterprise_id
      monthlyEnterpriseId.value = enterpriseId
      vatEnterpriseId.value = enterpriseId
      healthEnterpriseId.value = enterpriseId
      finEnterpriseId.value = enterpriseId
    }
    if (route.query.period) {
      monthlyPeriod.value = route.query.period
      vatPeriod.value = route.query.period
      healthPeriod.value = route.query.period
    }
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

.monthly-grid {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 18px;
  margin-top: 18px;
}
.monthly-hero {
  background: var(--panel);
  border-radius: 8px;
  padding: 24px;
  min-height: 190px;
}
.monthly-label {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--mute);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  margin-bottom: 12px;
}
.monthly-score {
  font-family: var(--font-mono);
  font-size: 72px;
  line-height: 1;
  color: var(--ink);
  margin-bottom: 16px;
}
.monthly-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.monthly-card {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
}
.monthly-card span {
  display: block;
  color: var(--mute);
  font-size: 12px;
  margin-bottom: 8px;
}
.monthly-card strong {
  font-family: var(--font-mono);
  color: var(--ink);
  font-size: 22px;
}
.risk-list {
  margin-top: 16px;
  display: grid;
  gap: 8px;
}
.risk-item {
  background: var(--warn-bg);
  color: var(--warn-fg);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
}

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
.completeness-grid {
  display: grid;
  grid-template-columns: 180px repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.completeness-card,
.data-check {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
  padding: 14px;
}
.completeness-card span,
.data-check p {
  display: block;
  color: var(--mute);
  font-size: 12px;
  margin: 6px 0 0;
}
.completeness-card strong {
  font-family: var(--font-mono);
  color: var(--ink);
  font-size: 34px;
}
.data-check strong {
  display: block;
  margin-top: 10px;
  color: var(--ink);
  font-size: 13px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0;
}
.report-sections {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}
.report-section {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--bg);
}
.report-section h3 {
  font-size: 15px;
  color: var(--ink);
  margin-bottom: 6px;
}
.report-section p {
  color: var(--ink-2);
  font-size: 13px;
  line-height: 1.6;
}

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
@media (max-width: 1100px) {
  .monthly-grid,
  .completeness-grid,
  .metric-grid {
    grid-template-columns: 1fr;
  }
  .health-hero,
  .fin-hero {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
