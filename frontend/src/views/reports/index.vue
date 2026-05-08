<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">财务报表</h1>
        <p class="page-desc">税务申报、财务健康诊断与融资评分报告</p>
      </div>
    </div>

    <el-card class="report-card">
      <el-tabs v-model="activeTab" class="report-tabs">
        <!-- 税务申报 -->
        <el-tab-pane label="税务申报" name="vat">
          <div class="tab-body">
            <div class="filter-row">
              <el-select v-model="vatEnterpriseId" placeholder="选择企业" style="width:240px" filterable @change="vatReportData = null">
                <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
              </el-select>
              <el-date-picker v-model="vatPeriod" type="month" placeholder="申报期" style="width:160px" format="YYYY-MM" value-format="YYYY-MM" />
              <el-button type="primary" :loading="vatLoading" @click="generateVatReport">生成报告</el-button>
              <el-button v-if="vatReportData" type="success" @click="exportVatExcel">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                导出 Excel
              </el-button>
            </div>

            <div v-if="vatReportData" class="vat-grid">
              <div class="vat-main-card">
                <div class="vat-amount-display">
                  <div class="vat-amount-label">应申报税额（含附加税）</div>
                  <div class="vat-amount-value">¥{{ Number(vatReportData.total_tax_and_surcharge || 0).toLocaleString() }}</div>
                  <div class="vat-period-badge">{{ vatPeriod }} 申报期</div>
                </div>
              </div>
              <div class="vat-breakdown-grid">
                <div class="vat-item">
                  <div class="vat-item-label">销售额（不含税）</div>
                  <div class="vat-item-value">¥{{ Number(vatReportData.sales_amount_excl_tax || 0).toLocaleString() }}</div>
                </div>
                <div class="vat-item">
                  <div class="vat-item-label">增值税率</div>
                  <div class="vat-item-value">{{ Number(vatReportData.tax_rate * 100).toFixed(1) }}%</div>
                </div>
                <div class="vat-item">
                  <div class="vat-item-label">增值税</div>
                  <div class="vat-item-value warn">¥{{ Number(vatReportData.tax_amount || 0).toLocaleString() }}</div>
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
            <el-empty v-else-if="!vatLoading" description="请选择企业和申报期后生成报告" />
            <el-skeleton v-if="vatLoading" :rows="4" animated />
          </div>
        </el-tab-pane>

        <!-- 财务健康 -->
        <el-tab-pane label="财务健康" name="health">
          <div class="tab-body">
            <div class="filter-row">
              <el-select v-model="healthEnterpriseId" placeholder="选择企业" style="width:240px" filterable @change="healthReportData = null">
                <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
              </el-select>
              <el-button type="primary" :loading="healthLoading" @click="generateHealthReport">生成报告</el-button>
              <el-button v-if="healthReportData" type="default" @click="exportPdf('health')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                导出 PDF
              </el-button>
            </div>

            <div v-if="healthReportData" class="health-result">
              <div class="health-hero">
                <div class="health-score-ring">
                  <svg viewBox="0 0 120 120" width="120" height="120">
                    <circle cx="60" cy="60" r="52" fill="none" stroke="#f0ece0" stroke-width="12"/>
                    <circle cx="60" cy="60" r="52" fill="none" stroke="#cc785c" stroke-width="12"
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
            <el-empty v-else-if="!healthLoading" description="请选择企业后生成报告" />
            <el-skeleton v-if="healthLoading" :rows="4" animated />
          </div>
        </el-tab-pane>

        <!-- 融资评分 -->
        <el-tab-pane label="融资评分" name="financing">
          <div class="tab-body">
            <div class="filter-row">
              <el-select v-model="finEnterpriseId" placeholder="选择企业" style="width:240px" filterable @change="finReportData = null">
                <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
              </el-select>
              <el-button type="primary" :loading="finLoading" @click="generateFinancingReport">生成报告</el-button>
              <el-button v-if="finReportData" type="default" @click="exportPdf('financing')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                导出 PDF
              </el-button>
            </div>

            <div v-if="finReportData" class="fin-result">
              <div class="fin-hero">
                <div class="fin-score-display">
                  <div class="fin-big-score" :style="{ color: finScoreColor }">{{ finReportData.score || '--' }}</div>
                  <div class="fin-score-sub">融资评分</div>
                  <el-tag :type="finScoreTag" class="fin-level-tag">{{ finReportData.level || '待评估' }}</el-tag>
                </div>
                <div class="fin-details">
                  <div class="fin-detail-item">
                    <span class="fd-label">信用等级</span>
                    <span class="fd-value">{{ finReportData.level || '--' }}</span>
                  </div>
                  <div class="fin-detail-item highlight">
                    <span class="fd-label">建议额度</span>
                    <span class="fd-value" style="color: #3d6b4a; font-size:18px">¥{{ Number(finReportData.estimated_loan_amount || 0).toLocaleString() }}</span>
                  </div>
                  <div class="fin-detail-item">
                    <span class="fd-label">报告编号</span>
                    <span class="fd-value mono" style="font-size:11px">{{ finReportData.score_id || '--' }}</span>
                  </div>
                </div>
              </div>
              <div class="fin-actions">
                <el-button type="primary" size="large" @click="applyLoan">申请贷款</el-button>
                <el-button size="large" @click="$router.push('/financing')">查看融资产品</el-button>
              </div>
            </div>
            <el-empty v-else-if="!finLoading" description="请选择企业后生成报告" />
            <el-skeleton v-if="finLoading" :rows="4" animated />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import api from '@/api'

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
  { name: '盈利能力', key: 'profitability', color: '#cc785c' },
  { name: '偿债能力', key: 'solvency', color: '#3d6b4a' },
  { name: '运营效率', key: 'operation_efficiency', color: '#a86a1f' },
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
      axisName: { color: '#5c5645', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e8e4da' } },
      splitArea: { areaStyle: { color: ['#faf9f6', '#f5f3ee'] } },
      radius: '65%'
    },
    series: [{
      type: 'radar',
      data: [{
        value: healthDimConfig.map(d => Math.round(scores[d.key] || 0)),
        name: '财务健康',
        areaStyle: { color: 'rgba(204, 120, 92, 0.25)' },
        lineStyle: { color: '#cc785c', width: 2 },
        itemStyle: { color: '#cc785c' }
      }]
    }]
  })
}

// Financing
const finEnterpriseId = ref('')
const finLoading = ref(false)
const finReportData = ref(null)
const finScoreTag = ref('')
const finScoreColor = ref('#cc785c')

const generateFinancingReport = async () => {
  if (!finEnterpriseId.value) { ElMessage.warning('请选择企业'); return }
  finLoading.value = true; finReportData.value = null
  try {
    const res = await api.post('/api/reports/financing/generate', { enterprise_id: finEnterpriseId.value })
    finReportData.value = res.data.data
    const score = res.data.data.score || 0
    if (score >= 70) { finScoreTag.value = 'success'; finScoreColor.value = '#3d6b4a' }
    else if (score >= 50) { finScoreTag.value = 'warning'; finScoreColor.value = '#a86a1f' }
    else { finScoreTag.value = 'danger'; finScoreColor.value = '#c0392b' }
  } catch (e) { ElMessage.error(e.response?.data?.detail || '生成失败') }
  finally { finLoading.value = false }
}

const applyLoan = () => ElMessage.success('贷款申请已提交，请等待银行客户经理联系')

// PDF
const exportPdf = async (type) => {
  if (typeof window.html2canvas === 'undefined' || typeof window.jspdf === 'undefined') {
    ElMessage.error('PDF 导出组件未加载')
    return
  }
  const { jsPDF } = window.jspdf
  ElMessage.info('正在生成 PDF...')
  try {
    const targetEl = document.querySelector('.tab-body')
    if (!targetEl) { ElMessage.error('未找到报告内容'); return }
    const canvas = await window.html2canvas(targetEl, { scale: 2, useCORS: true, backgroundColor: '#faf9f6' })
    const imgData = canvas.toDataURL('image/png')
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const pw = pdf.internal.pageSize.getWidth()
    const ph = pdf.internal.pageSize.getHeight()
    const ratio = canvas.height / canvas.width
    const imgH = pw * ratio
    let y = 0
    while (y < imgH) {
      pdf.addImage(imgData, 'PNG', 0, -y, pw, imgH)
      y += ph
      if (y < imgH) pdf.addPage()
    }
    pdf.save(`finwise-${type}-report.pdf`)
    ElMessage.success('PDF 已下载')
  } catch { ElMessage.error('PDF 导出失败') }
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
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-title { font-size: 20px; font-weight: 800; color: var(--color-text-primary); margin-bottom: 4px; }
.page-desc { font-size: 13px; color: var(--color-text-muted); }

.report-card { border-radius: var(--radius-lg) !important; }

.tab-body { padding-top: 16px; }

.filter-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

/* VAT */
.vat-grid { display: flex; flex-direction: column; gap: 16px; }
.vat-main-card {
  background: linear-gradient(135deg, #cc785c, #dda490);
  border-radius: var(--radius-lg);
  padding: 28px;
  color: white;
}
.vat-amount-label { font-size: 13px; opacity: 0.85; margin-bottom: 8px; }
.vat-amount-value { font-size: 36px; font-weight: 800; font-family: var(--font-mono); }
.vat-period-badge {
  display: inline-block;
  margin-top: 8px;
  background: rgba(255,255,255,0.25);
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 11px;
}
.vat-breakdown-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.vat-item {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 14px;
}
.vat-item-label { font-size: 12px; color: var(--color-text-muted); margin-bottom: 6px; }
.vat-item-value { font-size: 18px; font-weight: 700; color: var(--color-text-primary); font-family: var(--font-mono); }
.vat-item-value.warn { color: var(--color-warning); }

/* Health */
.health-result {}
.health-hero { display: flex; gap: 24px; align-items: center; margin-bottom: 24px; }
.health-score-ring { position: relative; display: flex; flex-direction: column; align-items: center; }
.ring-score { position: absolute; top: 50%; transform: translateY(-50%); font-size: 32px; font-weight: 800; color: #cc785c; }
.ring-label { font-size: 12px; color: var(--color-text-muted); margin-top: -8px; }
.health-chart-area { flex: 1; }
.health-dimensions { display: flex; flex-direction: column; gap: 10px; }
.dimension-row { display: flex; align-items: center; gap: 12px; }
.dim-name { width: 70px; font-size: 12px; color: var(--color-text-secondary); font-weight: 500; flex-shrink: 0; }
.dim-bar-wrap { flex: 1; height: 8px; background: var(--color-bg-alt); border-radius: 4px; overflow: hidden; }
.dim-bar { height: 100%; border-radius: 4px; transition: width 0.6s ease; }
.dim-score { width: 28px; font-size: 12px; font-weight: 700; text-align: right; flex-shrink: 0; }

/* Financing */
.fin-result {}
.fin-hero { display: flex; gap: 24px; align-items: center; background: var(--color-bg-alt); border-radius: var(--radius-lg); padding: 28px; margin-bottom: 20px; }
.fin-score-display { text-align: center; min-width: 120px; }
.fin-big-score { font-size: 64px; font-weight: 800; line-height: 1; }
.fin-score-sub { font-size: 13px; color: var(--color-text-muted); margin: 4px 0 12px; }
.fin-level-tag { font-weight: 600; }
.fin-details { flex: 1; display: flex; flex-direction: column; gap: 14px; }
.fin-detail-item { display: flex; justify-content: space-between; align-items: center; padding-bottom: 12px; border-bottom: 1px solid var(--color-border-light); }
.fin-detail-item:last-child { border-bottom: none; padding-bottom: 0; }
.fd-label { font-size: 13px; color: var(--color-text-muted); }
.fd-value { font-size: 14px; font-weight: 600; color: var(--color-text-primary); }
.fin-actions { display: flex; gap: 12px; }
</style>