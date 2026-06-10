<template>
  <div class="page">
    <div class="page-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/enterprises')">← 返回企业名册</button>
        <div class="page-eyebrow">§ 02 · ENTERPRISE DETAIL —</div>
        <h1 class="page-title">{{ financialDetail?.enterprise?.name || '企业详情' }}</h1>
        <p class="page-desc">按月查看数据完整度、银行流水、进销项明细和报告生成状态。</p>
      </div>
      <div v-if="financialDetail" class="header-actions">
        <span class="pill" :class="statusPillClass(financialDetail.enterprise.status)">
          {{ statusLabel(financialDetail.enterprise.status) }}
        </span>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="10" animated />

    <div v-else-if="financialDetail" class="detail-content">
      <div class="detail-meta">
        <div>
          <span>税号</span>
          <strong>{{ financialDetail.enterprise.tax_number || '—' }}</strong>
        </div>
        <div>
          <span>纳税人类型</span>
          <strong>{{ taxpayerTypeLabel(financialDetail.enterprise.taxpayer_type) }}</strong>
        </div>
        <div>
          <span>行业</span>
          <strong>{{ financialDetail.enterprise.industry || '—' }}</strong>
        </div>
        <div>
          <span>地区</span>
          <strong>{{ [financialDetail.enterprise.province, financialDetail.enterprise.city].filter(Boolean).join(' / ') || '—' }}</strong>
        </div>
      </div>

      <div class="finance-kpis">
        <div class="finance-kpi">
          <span>现金流入</span>
          <strong>¥{{ money(financialDetail.summary.cash_inflow) }}</strong>
        </div>
        <div class="finance-kpi">
          <span>现金流出</span>
          <strong>¥{{ money(financialDetail.summary.cash_outflow) }}</strong>
        </div>
        <div class="finance-kpi">
          <span>净现金流</span>
          <strong :class="Number(financialDetail.summary.net_cash_flow) < 0 ? 'neg' : 'pos'">¥{{ money(financialDetail.summary.net_cash_flow) }}</strong>
        </div>
        <div class="finance-kpi">
          <span>流水笔数</span>
          <strong>{{ financialDetail.summary.transaction_count }}</strong>
        </div>
      </div>

      <div class="detail-actions">
        <button class="btn secondary" @click="goImportData()">导入月数据</button>
        <button class="btn primary" @click="goGenerateReport()">生成财务健康报告</button>
      </div>

      <section class="detail-section">
        <div class="section-title">月度数据看板</div>
        <table class="table compact-table">
          <thead>
            <tr>
              <th>月份</th>
              <th>数据完整度</th>
              <th>数据项</th>
              <th style="text-align:right;">净现金流</th>
              <th style="text-align:right;">流水</th>
              <th style="text-align:right;">销项</th>
              <th style="text-align:right;">进项</th>
              <th style="text-align:right;">评分</th>
              <th style="text-align:right;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in financialDetail.monthly_summaries"
              :key="row.period"
              class="month-row"
              :class="{ selected: selectedMonthPeriod === row.period }"
            >
              <td><span class="mono">{{ row.period }}</span></td>
              <td>
                <div class="completion-cell">
                  <div class="completion-bar"><span :style="{ width: `${row.data_completion_rate || 0}%` }"></span></div>
                  <strong>{{ row.data_completion_rate || 0 }}%</strong>
                </div>
              </td>
              <td>
                <div class="data-tags">
                  <span
                    v-for="item in row.data_items"
                    :key="item.key"
                    class="data-dot"
                    :class="item.status === 'READY' ? 'ready' : 'missing'"
                    :title="`${item.label}：${item.message}`"
                  >{{ shortDataLabel(item.label) }}</span>
                </div>
              </td>
              <td style="text-align:right;" :class="Number(row.net_cash_flow) < 0 ? 'neg' : 'pos'">¥{{ money(row.net_cash_flow) }}</td>
              <td style="text-align:right;">{{ row.transaction_count }}</td>
              <td style="text-align:right;">{{ row.sales_invoice_count || 0 }}</td>
              <td style="text-align:right;">{{ row.purchase_invoice_count || 0 }}</td>
              <td style="text-align:right;">{{ row.overall_score ?? '—' }}</td>
              <td style="text-align:right;">
                <button class="btn ghost detail-mini-btn" :disabled="monthDetailLoading" @click="viewMonthDetail(row)">详情</button>
              </td>
            </tr>
            <tr v-if="financialDetail.monthly_summaries.length === 0">
              <td colspan="9" style="text-align:center;color:var(--mute);padding:28px;">暂无月度财务数据</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="monthDetailLoading" class="detail-section">
        <el-skeleton :rows="6" animated />
      </section>

      <section v-else-if="monthDetail" class="detail-section month-detail-section">
        <div class="month-detail-head">
          <div>
            <div class="section-title">{{ selectedMonthPeriod }} 月度详情</div>
            <p>本月数据完整度 {{ selectedMonthSummary?.data_completion_rate || 0 }}%，可直接查看明细或生成财务健康报告。</p>
          </div>
          <div class="detail-actions compact-actions">
            <button class="btn secondary" @click="goImportData(selectedMonthPeriod)">补充月数据</button>
            <button class="btn primary" @click="goGenerateReport(selectedMonthPeriod)">生成报告</button>
          </div>
        </div>

        <div class="month-kpis">
          <div>
            <span>现金流入</span>
            <strong>¥{{ money(monthDetail.summary.cash_inflow) }}</strong>
          </div>
          <div>
            <span>现金流出</span>
            <strong>¥{{ money(monthDetail.summary.cash_outflow) }}</strong>
          </div>
          <div>
            <span>净现金流</span>
            <strong :class="Number(monthDetail.summary.net_cash_flow) < 0 ? 'neg' : 'pos'">¥{{ money(monthDetail.summary.net_cash_flow) }}</strong>
          </div>
          <div>
            <span>发票行数</span>
            <strong>{{ monthDetail.summary.invoice_count }}</strong>
          </div>
        </div>

        <div class="month-subsection">
          <div class="subsection-title">本月数据状态</div>
          <div class="detail-check-grid">
            <div v-for="item in selectedMonthSummary?.data_items || []" :key="item.key" class="detail-check">
              <span class="pill" :class="item.status === 'READY' ? 'pill--ok' : 'pill--warn'">{{ item.status === 'READY' ? '已就绪' : '待补充' }}</span>
              <strong>{{ item.label }}</strong>
              <p>{{ item.message }} · {{ item.count }} 条</p>
            </div>
          </div>
        </div>

        <div class="detail-columns">
          <div class="month-subsection">
            <div class="subsection-title">本月银行流水</div>
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>摘要</th>
                  <th style="text-align:right;">借方</th>
                  <th style="text-align:right;">贷方</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="tx in monthDetail.recent_transactions" :key="tx.id">
                  <td><span class="mono">{{ tx.transaction_date }}</span></td>
                  <td class="summary-cell">{{ tx.summary }}</td>
                  <td style="text-align:right;">{{ tx.debit_amount ? `¥${money(tx.debit_amount)}` : '—' }}</td>
                  <td style="text-align:right;">{{ tx.credit_amount ? `¥${money(tx.credit_amount)}` : '—' }}</td>
                </tr>
                <tr v-if="monthDetail.recent_transactions.length === 0">
                  <td colspan="4" style="text-align:center;color:var(--mute);padding:28px;">暂无银行流水</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="month-subsection">
            <div class="subsection-title">本月进销项明细</div>
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>方向</th>
                  <th>名称</th>
                  <th style="text-align:right;">金额</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="invoice in monthDetail.recent_invoices" :key="invoice.id">
                  <td><span class="mono">{{ invoice.issue_date }}</span></td>
                  <td><span class="pill pill--idle invoice-dir">{{ directionLabel(invoice.direction || invoice.invoice_type) }}</span></td>
                  <td class="summary-cell">{{ invoice.item_name || invoice.buyer_name || invoice.seller_name || '—' }}</td>
                  <td style="text-align:right;">¥{{ money(invoice.amount || invoice.total_amount) }}</td>
                </tr>
                <tr v-if="monthDetail.recent_invoices.length === 0">
                  <td colspan="4" style="text-align:center;color:var(--mute);padding:28px;">暂无进销项明细</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const enterpriseId = computed(() => route.params.id)
const loading = ref(false)
const financialDetail = ref(null)
const monthDetail = ref(null)
const monthDetailLoading = ref(false)
const selectedMonthPeriod = ref('')

const statusLabel = (s) => ({ ACTIVE: '正常', SUSPENDED: '暂停', CANCELLED: '注销' }[s] || s)
const statusPillClass = (s) => ({ ACTIVE: 'pill--ok', SUSPENDED: 'pill--warn', CANCELLED: 'pill--idle' }[s] || 'pill--idle')
const taxpayerTypeLabel = (type) => ({ GENERAL: '一般纳税人', SMALL: '小规模纳税人' }[type] || type || '—')
const money = (value) => Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const shortDataLabel = (label) => ({
  企业基础信息: '企',
  银行流水: '流',
  销项明细: '销',
  进项明细: '进',
  '资产负债表/利润表': '表'
}[label] || label.slice(0, 1))
const directionLabel = (direction) => ({
  SALES: '销项',
  OUTPUT: '销项',
  PURCHASE: '进项',
  INPUT: '进项'
}[direction] || '未知')

const selectedMonthSummary = computed(() => {
  if (!financialDetail.value || !selectedMonthPeriod.value) return null
  return financialDetail.value.monthly_summaries.find(item => item.period === selectedMonthPeriod.value) || null
})

const fetchFinancialDetail = async () => {
  loading.value = true
  try {
    const res = await api.get(`/enterprises/${enterpriseId.value}/financials`)
    financialDetail.value = res.data
    const firstMonth = res.data.monthly_summaries?.[0]
    if (firstMonth) await viewMonthDetail(firstMonth)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载企业详情失败')
    router.push('/enterprises')
  } finally {
    loading.value = false
  }
}

const viewMonthDetail = async (row) => {
  if (!row?.period) return
  const [periodYear, periodMonth] = row.period.split('-').map(Number)
  selectedMonthPeriod.value = row.period
  monthDetail.value = null
  monthDetailLoading.value = true
  try {
    const res = await api.get(`/enterprises/${enterpriseId.value}/financials`, {
      params: { period_year: periodYear, period_month: periodMonth, limit: 100 }
    })
    monthDetail.value = res.data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载月度详情失败')
  } finally {
    monthDetailLoading.value = false
  }
}

const goImportData = (period = '') => {
  const query = { enterprise_id: enterpriseId.value }
  if (period) query.period = period
  router.push({ path: '/invoices', query })
}

const goGenerateReport = (period = '') => {
  const query = { tab: 'health', enterprise_id: enterpriseId.value }
  if (period) query.period = period
  router.push({ path: '/reports', query })
}

onMounted(fetchFinancialDetail)
</script>

<style scoped>
.page { width: 100%; }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  margin-bottom: 28px;
}
.header-left { min-width: 0; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.back-btn {
  border: 0;
  background: transparent;
  color: var(--mute);
  font-size: 13px;
  padding: 0;
  margin-bottom: 14px;
  cursor: pointer;
}
.back-btn:hover { color: var(--ink); }
.page-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 8px;
}
.page-title {
  font-size: 44px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin-bottom: 8px;
  line-height: 1.12;
}
.page-desc {
  font-size: 13.5px;
  color: var(--mute);
  line-height: 1.7;
}
.detail-content {
  display: grid;
  gap: 18px;
}
.detail-meta,
.finance-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.detail-meta > div,
.finance-kpi,
.detail-section {
  background: var(--panel);
  border-radius: 8px;
}
.detail-meta > div,
.finance-kpi {
  padding: 14px;
}
.detail-meta span,
.finance-kpi span {
  display: block;
  color: var(--mute);
  font-size: 12px;
  margin-bottom: 6px;
}
.detail-meta strong,
.finance-kpi strong {
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
  word-break: break-all;
}
.finance-kpi strong {
  font-family: var(--font-mono);
  font-size: 22px;
}
.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.detail-section {
  padding: 16px;
}
.section-title {
  font-size: 15px;
  color: var(--ink);
  font-weight: 600;
  margin-bottom: 12px;
}
.compact-table {
  background: transparent;
}
.compact-table th,
.compact-table td {
  padding: 10px 8px;
  font-size: 12px;
}
.month-row.selected {
  background: var(--bg);
}
.completion-cell {
  display: grid;
  grid-template-columns: minmax(72px, 1fr) 38px;
  align-items: center;
  gap: 8px;
}
.completion-cell strong {
  font-family: var(--font-mono);
  color: var(--ink);
  font-size: 12px;
}
.completion-bar {
  height: 6px;
  border-radius: 999px;
  background: var(--line-soft);
  overflow: hidden;
}
.completion-bar span {
  display: block;
  height: 100%;
  min-width: 4px;
  border-radius: inherit;
  background: var(--accent);
}
.data-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.data-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid var(--line);
}
.data-dot.ready {
  background: var(--ok-bg);
  color: var(--ok-fg);
  border-color: transparent;
}
.data-dot.missing {
  background: var(--warn-bg);
  color: var(--warn-fg);
  border-color: transparent;
}
.detail-mini-btn {
  height: 26px;
  padding: 0 8px;
  font-size: 12px;
}
.summary-cell {
  max-width: 360px;
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.month-detail-section {
  display: grid;
  gap: 16px;
}
.month-detail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.month-detail-head p {
  margin: -4px 0 0;
  color: var(--mute);
  font-size: 12.5px;
}
.compact-actions {
  flex-shrink: 0;
}
.month-kpis,
.detail-check-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.month-kpis > div,
.detail-check {
  background: var(--bg);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 12px;
}
.month-kpis span,
.detail-check p {
  display: block;
  color: var(--mute);
  font-size: 12px;
}
.month-kpis strong {
  display: block;
  margin-top: 6px;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 18px;
}
.month-subsection {
  min-width: 0;
}
.subsection-title {
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 10px;
}
.detail-check {
  display: grid;
  gap: 6px;
}
.detail-check strong {
  color: var(--ink);
  font-size: 13px;
}
.detail-check p {
  margin: 0;
  line-height: 1.5;
}
.detail-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: 16px;
}
.invoice-dir {
  font-size: 11px;
}
.pos { color: var(--ok-fg); }
.neg { color: var(--alert-fg); }
@media (max-width: 1100px) {
  .detail-meta,
  .finance-kpis,
  .month-kpis,
  .detail-check-grid,
  .detail-columns {
    grid-template-columns: 1fr;
  }
}
</style>
