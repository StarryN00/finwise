<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <span style="font-size: 16px; font-weight: 600">报告管理</span>
      </template>
      <el-tabs v-model="activeTab" class="report-tabs">

        <!-- 税务申报 Tab -->
        <el-tab-pane label="税务申报" name="vat">
          <div class="tab-content">
            <el-form :inline="true" style="margin-bottom: 16px">
              <el-form-item label="选择企业">
                <el-select v-model="vatEnterpriseId" placeholder="请选择企业" style="width: 260px" filterable @change="onVatEnterpriseChange">
                  <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="申报期">
                <el-date-picker v-model="vatPeriod" type="month" placeholder="选择月份" style="width: 160px" format="YYYY-MM" value-format="YYYY-MM" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="vatLoading" @click="generateVatReport">生成报告</el-button>
                <el-button v-if="vatReportData" type="success" @click="exportVatExcel">导出 Excel</el-button>
              </el-form-item>
            </el-form>

            <div v-if="vatReportData" class="vat-summary">
              <el-row :gutter="16">
                <el-col :span="6">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">销售额（不含税）</div>
                    <div class="summary-value primary">¥{{ Number(vatReportData.sales_amount_excl_tax || 0).toLocaleString() }}</div>
                  </el-card>
                </el-col>
                <el-col :span="6">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">税率</div>
                    <div class="summary-value">{{ Number(vatReportData.tax_rate * 100).toFixed(1) }}%</div>
                  </el-card>
                </el-col>
                <el-col :span="6">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">增值税</div>
                    <div class="summary-value warn">¥{{ Number(vatReportData.tax_amount || 0).toLocaleString() }}</div>
                  </el-card>
                </el-col>
                <el-col :span="6">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">合计（含附加税）</div>
                    <div class="summary-value danger">¥{{ Number(vatReportData.total_tax_and_surcharge || 0).toLocaleString() }}</div>
                  </el-card>
                </el-col>
              </el-row>
              <el-row :gutter="16" style="margin-top: 12px">
                <el-col :span="8">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">城建税</div>
                    <div class="summary-value">¥{{ Number(vatReportData.urban_construction_tax || 0).toLocaleString() }}</div>
                  </el-card>
                </el-col>
                <el-col :span="8">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">教育费附加</div>
                    <div class="summary-value">¥{{ Number(vatReportData.education_surcharge || 0).toLocaleString() }}</div>
                  </el-card>
                </el-col>
                <el-col :span="8">
                  <el-card shadow="hover" class="summary-card">
                    <div class="summary-label">地方教育附加</div>
                    <div class="summary-value">¥{{ Number(vatReportData.local_education_surcharge || 0).toLocaleString() }}</div>
                  </el-card>
                </el-col>
              </el-row>
            </div>
            <el-empty v-else-if="!vatLoading" description="请选择企业和申报期后生成报告" />
            <el-skeleton v-if="vatLoading" :rows="4" animated />
          </div>
        </el-tab-pane>

        <!-- 财务健康 Tab -->
        <el-tab-pane label="财务健康" name="health">
          <div class="tab-content">
            <el-form :inline="true" style="margin-bottom: 16px">
              <el-form-item label="选择企业">
                <el-select v-model="healthEnterpriseId" placeholder="请选择企业" style="width: 260px" filterable>
                  <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="healthLoading" @click="generateHealthReport">生成报告</el-button>
                <el-button v-if="healthReportData" @click="exportPdf('health')">导出 PDF</el-button>
              </el-form-item>
            </el-form>

            <div v-if="healthReportData" class="health-result">
              <el-row :gutter="24">
                <el-col :span="8" style="text-align: center">
                  <div class="health-score">{{ healthReportData.financing_score || '--' }}</div>
                  <div class="health-score-label">融资评分</div>
                </el-col>
                <el-col :span="16">
                  <div ref="radarChartRef" style="width: 100%; height: 280px" />
                </el-col>
              </el-row>
              <el-divider />
              <el-row :gutter="12">
                <el-col v-for="dim in healthDimensions" :key="dim.name" :span="8" style="margin-bottom: 12px">
                  <div class="dimension-card">
                    <div class="dimension-name">{{ dim.name }}</div>
                    <el-progress :percentage="dim.score" :color="dim.color" :stroke-width="8" />
                  </div>
                </el-col>
              </el-row>
            </div>
            <el-empty v-else-if="!healthLoading" description="请选择企业后生成报告" />
            <el-skeleton v-if="healthLoading" :rows="4" animated />
          </div>
        </el-tab-pane>

        <!-- 融资评分 Tab -->
        <el-tab-pane label="融资评分" name="financing">
          <div class="tab-content">
            <el-form :inline="true" style="margin-bottom: 16px">
              <el-form-item label="选择企业">
                <el-select v-model="finEnterpriseId" placeholder="请选择企业" style="width: 260px" filterable>
                  <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="finLoading" @click="generateFinancingReport">生成报告</el-button>
                <el-button v-if="finReportData" @click="exportPdf('financing')">导出 PDF</el-button>
              </el-form-item>
            </el-form>

            <div v-if="finReportData" class="fin-result">
              <el-row :gutter="24">
                <el-col :span="8">
                  <el-card shadow="hover" class="fin-score-card">
                    <div class="fin-score">{{ finReportData.score || '--' }}</div>
                    <div class="fin-score-label">融资评分</div>
                    <el-tag :type="finScoreTag" style="margin-top: 8px">{{ finReportData.level || '待评估' }}</el-tag>
                  </el-card>
                </el-col>
                <el-col :span="8">
                  <el-card shadow="hover" class="fin-info-card">
                    <div class="fin-info-row"><span class="fin-info-label">信用等级</span><span class="fin-info-value">{{ finReportData.level || '--' }}</span></div>
                    <el-divider style="margin: 12px 0" />
                    <div class="fin-info-row"><span class="fin-info-label">建议额度</span><span class="fin-info-value highlight">¥{{ Number(finReportData.estimated_loan_amount || 0).toLocaleString() }}</span></div>
                  </el-card>
                </el-col>
                <el-col :span="8">
                  <el-card shadow="hover" class="fin-info-card">
                    <div class="fin-info-row"><span class="fin-info-label">评分区间</span><span class="fin-info-value">{{ finReportData.score || '--' }}</span></div>
                    <el-divider style="margin: 12px 0" />
                    <div class="fin-info-row"><span class="fin-info-label">报告编号</span><span class="fin-info-value" style="font-size: 11px">{{ finReportData.score_id || '--' }}</span></div>
                  </el-card>
                </el-col>
              </el-row>
              <div style="margin-top: 20px; text-align: center">
                <el-button type="primary" size="large" @click="applyLoan">申请贷款</el-button>
                <el-button size="large" @click="viewFinancingProducts">查看适配融资产品</el-button>
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
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import api from '@/api'

const router = useRouter()
const activeTab = ref('vat')
const enterprises = ref([])

// --- VAT ---
const vatEnterpriseId = ref('')
const vatPeriod = ref('')
const vatLoading = ref(false)
const vatReportData = ref(null)

const generateVatReport = async () => {
  if (!vatEnterpriseId.value || !vatPeriod.value) {
    ElMessage.warning('请选择企业和申报期')
    return
  }
  vatLoading.value = true
  try {
    const [year, month] = vatPeriod.value.split('-')
    const res = await api.post('/api/reports/vat/generate', {
      enterprise_id: vatEnterpriseId.value,
      period_year: parseInt(year),
      period_month: parseInt(month)
    })
    vatReportData.value = res.data.data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    vatLoading.value = false
  }
}

const exportVatExcel = () => {
  ElMessage.info('Excel 导出功能开发中')
}

const onVatEnterpriseChange = () => {
  vatReportData.value = null
}

// --- Health ---
const healthEnterpriseId = ref('')
const healthLoading = ref(false)
const healthReportData = ref(null)
const radarChartRef = ref(null)
let radarChart = null

const healthDimensions = ref([])

const healthDimConfig = [
  { name: '盈利能力', key: 'profitability', color: '#67c23a' },
  { name: '偿债能力', key: 'solvency', color: '#409eff' },
  { name: '运营效率', key: 'operation_efficiency', color: '#e6a23c' },
  { name: '成长性', key: 'growth', color: '#f56c6c' },
  { name: '现金流', key: 'cash_flow', color: '#9b59b6' }
]

const generateHealthReport = async () => {
  if (!healthEnterpriseId.value) {
    ElMessage.warning('请选择企业')
    return
  }
  healthLoading.value = true
  healthReportData.value = null
  try {
    const res = await api.post('/api/reports/health/generate', {
      enterprise_id: healthEnterpriseId.value,
      report_type: 'FULL'
    })
    healthReportData.value = res.data.data
    buildHealthDimensions(res.data.data)
    await nextTick()
    renderRadarChart(res.data.data)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    healthLoading.value = false
  }
}

const buildHealthDimensions = (data) => {
  const scores = data.dimensions || {}
  healthDimensions.value = healthDimConfig.map(d => ({
    name: d.name,
    score: Math.round(scores[d.key] || 0),
    color: d.color
  }))
}

const renderRadarChart = (data) => {
  if (!radarChartRef.value) return
  if (radarChart) { radarChart.dispose() }
  radarChart = echarts.init(radarChartRef.value)
  const scores = data.dimensions || {}
  const option = {
    backgroundColor: 'transparent',
    legend: { show: false },
    radar: {
      indicator: healthDimConfig.map(d => ({ name: d.name, max: 100 })),
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: '#666' },
      splitLine: { lineStyle: { color: '#e0e0e0' } },
      splitArea: { areaStyle: { color: ['#fafafa', '#fff'] } }
    },
    series: [{
      type: 'radar',
      data: [{
        value: healthDimConfig.map(d => Math.round(scores[d.key] || 0)),
        name: '财务健康',
        areaStyle: { color: 'rgba(102, 126, 234, 0.3)' },
        lineStyle: { color: '#667eea', width: 2 },
        itemStyle: { color: '#667eea' }
      }]
    }]
  }
  radarChart.setOption(option)
}

// --- Financing ---
const finEnterpriseId = ref('')
const finLoading = ref(false)
const finReportData = ref(null)

const finScoreTag = ref('')

const generateFinancingReport = async () => {
  if (!finEnterpriseId.value) {
    ElMessage.warning('请选择企业')
    return
  }
  finLoading.value = true
  finReportData.value = null
  try {
    const res = await api.post('/api/reports/financing/generate', {
      enterprise_id: finEnterpriseId.value
    })
    finReportData.value = res.data.data
    const score = res.data.data.score || 0
    finScoreTag.value = score >= 70 ? 'success' : score >= 50 ? 'warning' : 'danger'
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    finLoading.value = false
  }
}

const applyLoan = () => {
  ElMessage.success('贷款申请已提交，请等待银行客户经理联系')
}

const viewFinancingProducts = () => {
  router.push('/financing')
}

// --- PDF Export ---
const exportPdf = async (type) => {
  if (typeof window.html2canvas === 'undefined' || typeof window.jspdf === 'undefined') {
    ElMessage.error('PDF 导出组件加载失败，请检查网络')
    return
  }
  const { jsPDF } = window.jspdf
  ElMessage.info('正在生成 PDF...')
  try {
    const targetEl = document.querySelector('.tab-content')
    if (!targetEl) {
      ElMessage.error('未找到报告内容区域')
      return
    }
    const canvas = await window.html2canvas(targetEl, { scale: 2, useCORS: true, backgroundColor: '#ffffff' })
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
    pdf.save(`finwise-report-${type}.pdf`)
    ElMessage.success('PDF 已下载')
  } catch (e) {
    ElMessage.error('PDF 导出失败')
  }
}

// --- Fetch enterprises ---
const fetchEnterprises = async () => {
  try {
    const res = await api.get('/api/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
  } catch (e) {}
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page-container { width: 100%; }
.tab-content { padding-top: 12px; }
.vat-summary { margin-top: 16px; }
.summary-card { text-align: center; }
.summary-label { font-size: 13px; color: #999; margin-bottom: 8px }
.summary-value { font-size: 20px; font-weight: 700; color: #333 }
.summary-value.primary { color: #409eff; }
.summary-value.warn { color: #e6a23c; }
.summary-value.danger { color: #f56c6c; }
.health-score { font-size: 64px; font-weight: 800; color: #667eea; line-height: 1.2; }
.health-score-label { font-size: 14px; color: #999; margin-top: 4px; }
.dimension-card { background: #fafafa; border-radius: 8px; padding: 12px; }
.dimension-name { font-size: 13px; color: #666; margin-bottom: 8px; }
.fin-score-card { text-align: center; padding: 20px 0; }
.fin-score { font-size: 56px; font-weight: 800; color: #667eea; }
.fin-score-label { font-size: 14px; color: #999; margin-top: 4px; }
.fin-info-card { padding: 16px; }
.fin-info-row { display: flex; justify-content: space-between; align-items: center; }
.fin-info-label { color: #999; font-size: 13px; }
.fin-info-value { font-weight: 600; color: #333; }
.fin-info-value.highlight { color: #67c23a; font-size: 18px; }
</style>
