<template>
  <div class="page">
    <!-- Editorial Header -->
    <div class="page-header">
      <div class="header-left">
        <div class="page-eyebrow">§ 03 · INVOICE CENTER —</div>
        <h1 class="page-title">发票管理</h1>
        <p class="page-desc">管理企业进项与销项发票，记录银行流水并进行智能匹配。</p>
      </div>
    </div>

    <!-- Segmented Control -->
    <div class="seg-wrap">
      <div class="seg">
        <button :class="{ on: activeTab === 'invoices' }" @click="activeTab = 'invoices'">发票管理</button>
        <button :class="{ on: activeTab === 'bank' }" @click="activeTab = 'bank'">银行流水</button>
      </div>
    </div>

      <!-- Invoice Tab -->
      <div v-if="activeTab === 'invoices'" class="tab-body">
        <div class="upload-row">
          <div class="upload-section">
            <div class="upload-label">选择企业</div>
            <select v-model="invoiceEnterpriseId" class="input enterprise-select">
              <option value="">请先选择企业</option>
              <option v-for="e in enterprises" :key="e.id" :value="e.id">{{ e.name }}</option>
            </select>
          </div>
          <div class="upload-dropzone" :class="{ dragging: isDragging }"
            @dragover.prevent="isDragging = true"
            @dragleave="isDragging = false"
            @drop.prevent="onDrop"
          >
            <div class="dropzone-icon">↑</div>
            <div class="dropzone-main">拖放 Excel 文件至此处</div>
            <div class="dropzone-sub">或点击选择文件</div>
            <input type="file" accept=".xls,.xlsx,.csv" class="file-input" @change="onInvoiceFileChange" />
          </div>
          <div class="upload-actions">
            <div v-if="invoiceFileName" class="file-name">{{ invoiceFileName }}</div>
            <button class="btn primary" :disabled="!invoiceFile || !invoiceEnterpriseId" :loading="invoiceUploading" @click="submitInvoiceImport">
              导入发票
            </button>
          </div>
        </div>

        <div class="upload-meta">支持 .xls · .xlsx · .csv 格式，文件不超过 10MB</div>

        <div class="section-divider"></div>

        <!-- Invoice Table -->
        <div v-if="invoiceList.length > 0">
          <div class="result-count">共 {{ invoiceList.length }} 条发票记录</div>
          <table class="table">
            <thead>
              <tr>
                <th>发票号码</th>
                <th>开票日期</th>
                <th style="text-align: right;">金额（含税）</th>
                <th style="text-align: right;">税额</th>
                <th>类型</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in invoiceList" :key="row.invoiceNumber">
                <td><span class="mono" style="font-size: 12px;">{{ row.invoiceNumber }}</span></td>
                <td><span class="mono" style="font-size: 12px; color: var(--mute);">{{ row.date }}</span></td>
                <td style="text-align: right;"><span class="mono">¥{{ Number(row.amount).toLocaleString() }}</span></td>
                <td style="text-align: right;"><span class="mono">¥{{ Number(row.taxAmount || 0).toLocaleString() }}</span></td>
                <td>
                  <span class="pill" :class="row.type === 'SALES' ? 'pill--ok' : 'pill--info'">
                    {{ row.type === 'SALES' ? '销项' : '进项' }}
                  </span>
                </td>
                <td>
                  <span class="pill" :class="row.status === 'VALID' ? 'pill--ok' : 'pill--idle'">
                    {{ row.status === 'VALID' ? '有效' : '作废' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state">
          <div class="empty-icon">⊙</div>
          <div class="empty-text">暂无发票数据，请先上传导入</div>
        </div>
      </div>

      <!-- Bank Tab -->
      <div v-if="activeTab === 'bank'" class="tab-body">
        <div class="upload-row">
          <div class="upload-section">
            <div class="upload-label">选择企业</div>
            <select v-model="bankEnterpriseId" class="input enterprise-select">
              <option value="">请先选择企业</option>
              <option v-for="e in enterprises" :key="e.id" :value="e.id">{{ e.name }}</option>
            </select>
          </div>
          <div class="upload-dropzone" :class="{ dragging: isBankDragging }"
            @dragover.prevent="isBankDragging = true"
            @dragleave="isBankDragging = false"
            @drop.prevent="onBankDrop"
          >
            <div class="dropzone-icon">↑</div>
            <div class="dropzone-main">拖放银行流水 Excel 文件</div>
            <div class="dropzone-sub">或点击选择文件</div>
            <input type="file" accept=".xls,.xlsx,.csv" class="file-input" @change="onBankFileChange" />
          </div>
          <div class="upload-actions">
            <div v-if="bankFileName" class="file-name">{{ bankFileName }}</div>
            <button class="btn primary" :disabled="!bankFile || !bankEnterpriseId" :loading="bankUploading" @click="submitBankImport">
              上传
            </button>
          </div>
        </div>

        <!-- Parse status -->
        <div v-if="importBatchId" class="parse-section">
          <div class="parse-status-row">
            <span class="pill" :class="parseStatusClass">
              {{ parseStatusText }}
            </span>
            <div class="parse-actions">
              <button class="btn secondary" :loading="parseLoading" :disabled="parseStatus === 'PROCESSING'" @click="runAiParse">
                {{ parseStatus === 'PENDING' ? '开始 AI 解析' : '重新解析' }}
              </button>
              <button class="btn secondary" :loading="matchLoading" :disabled="parseStatus !== 'COMPLETED'" @click="runMatch">
                发票匹配
              </button>
            </div>
          </div>

          <!-- Parsed Transactions -->
          <div v-if="parsedTransactions.length > 0" class="result-block">
            <div class="result-count">识别流水 {{ parsedTransactions.length }} 笔</div>
            <table class="table">
              <thead>
                <tr>
                  <th>交易日期</th>
                  <th>摘要</th>
                  <th style="text-align: right;">金额</th>
                  <th style="text-align: right;">余额</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in parsedTransactions" :key="i">
                  <td><span class="mono" style="font-size: 12px; color: var(--mute);">{{ row.date }}</span></td>
                  <td style="color: var(--ink-2);">{{ row.description }}</td>
                  <td style="text-align: right;"><span class="mono">¥{{ Number(row.amount).toLocaleString() }}</span></td>
                  <td style="text-align: right;"><span class="mono">¥{{ Number(row.balance || 0).toLocaleString() }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Match Results -->
          <div v-if="matchResults.length > 0" class="result-block">
            <div class="result-count" style="font-weight: 600;">匹配结果</div>
            <table class="table">
              <thead>
                <tr>
                  <th>发票号</th>
                  <th style="text-align: right;">金额</th>
                  <th>交易日期</th>
                  <th>摘要</th>
                  <th>匹配置信度</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in matchResults" :key="row.invoiceNumber">
                  <td><span class="mono" style="font-size: 12px;">{{ row.invoiceNumber }}</span></td>
                  <td style="text-align: right;"><span class="mono">¥{{ Number(row.amount).toLocaleString() }}</span></td>
                  <td><span class="mono" style="font-size: 12px; color: var(--mute);">{{ row.date }}</span></td>
                  <td style="color: var(--ink-2);">{{ row.description }}</td>
                  <td>
                    <span class="pill" :class="confidencePillClass(row.confidence)">
                      {{ (row.confidence * 100).toFixed(0) }}%
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="match-summary">未匹配流水：{{ unmatchedTransactions }} 笔　未匹配发票：{{ unmatchedInvoices }} 笔</div>
          </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const activeTab = ref('invoices')
const isDragging = ref(false)
const isBankDragging = ref(false)

// Enterprise list
const enterprises = ref([])
const invoiceEnterpriseId = ref('')
const bankEnterpriseId = ref('')

// Invoice import
const invoiceFile = ref(null)
const invoiceFileName = ref('')
const invoiceUploading = ref(false)
const invoiceList = ref([])

const onInvoiceFileChange = (e) => {
  const f = e.target.files[0]
  if (f) { invoiceFile.value = f; invoiceFileName.value = f.name }
}
const onDrop = (e) => { isDragging.value = false; const f = e.dataTransfer.files[0]; if (f) { invoiceFile.value = f; invoiceFileName.value = f.name } }

const submitInvoiceImport = async () => {
  if (!invoiceFile.value) return
  invoiceUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', invoiceFile.value)
    const res = await api.post(`/api/import/invoices?enterprise_id=${invoiceEnterpriseId.value}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success(`发票导入成功，共 ${res.data.total_rows} 条`)
    invoiceList.value = res.data.invoices || []
    invoiceFile.value = null
    invoiceFileName.value = ''
  } catch (e) { ElMessage.error(e.response?.data?.detail || '发票导入失败') }
  finally { invoiceUploading.value = false }
}

// Bank import
const bankFile = ref(null)
const bankFileName = ref('')
const bankUploading = ref(false)
const importBatchId = ref('')
const parseStatus = ref('PENDING')
const parseLoading = ref(false)
const matchLoading = ref(false)
const parsedTransactions = ref([])
const matchResults = ref([])
const unmatchedTransactions = ref(0)
const unmatchedInvoices = ref(0)

const onBankFileChange = (e) => {
  const f = e.target.files[0]
  if (f) { bankFile.value = f; bankFileName.value = f.name }
}
const onBankDrop = (e) => { isBankDragging.value = false; const f = e.dataTransfer.files[0]; if (f) { bankFile.value = f; bankFileName.value = f.name } }

const submitBankImport = async () => {
  if (!bankFile.value) return
  bankUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', bankFile.value)
    const res = await api.post(`/api/import/bank_statements?enterprise_id=${bankEnterpriseId.value}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    importBatchId.value = res.data.batch_id
    parseStatus.value = 'PENDING'
    parsedTransactions.value = []
    matchResults.value = []
    ElMessage.success('银行流水上传成功，可点击"开始 AI 解析"')
    bankFile.value = null
    bankFileName.value = ''
  } catch (e) { ElMessage.error(e.response?.data?.detail || '上传失败') }
  finally { bankUploading.value = false }
}

const parseStatusClass = computed(() => ({
  'pill--ok': parseStatus.value === 'COMPLETED',
  'pill--warn': parseStatus.value === 'PROCESSING',
  'pill--info': parseStatus.value === 'PENDING'
}))
const parseStatusText = computed(() => ({
  PENDING: '等待解析',
  PROCESSING: 'AI 解析中...',
  COMPLETED: '解析完成'
}[parseStatus.value]))

const runAiParse = async () => {
  if (!importBatchId.value || !bankEnterpriseId.value) return
  parseLoading.value = true
  parseStatus.value = 'PROCESSING'
  try {
    await api.post('/api/parse/bank_statement', { enterprise_id: bankEnterpriseId.value, file_id: importBatchId.value })
    try {
      const previewRes = await api.get(`/api/parse/bank_statement/preview/${importBatchId.value}`, {
        params: { enterprise_id: bankEnterpriseId.value }
      })
      parsedTransactions.value = previewRes.data.transactions || []
    } catch { parsedTransactions.value = [] }
    parseStatus.value = 'COMPLETED'
  } catch (e) {
    parseStatus.value = 'PENDING'
    ElMessage.error(e.response?.data?.detail || 'AI 解析失败')
  } finally { parseLoading.value = false }
}

const runMatch = async () => {
  if (!bankEnterpriseId.value) return
  matchLoading.value = true
  try {
    const res = await api.post('/api/parse/match', { enterprise_id: bankEnterpriseId.value })
    matchResults.value = (res.data.candidates || []).map(c => ({
      invoiceNumber: c.invoice_number || `INV-${c.invoice_index}`,
      amount: c.invoice_total_amount || (c.transaction_debit_amount || c.transaction_credit_amount || 0),
      date: c.invoice_issue_date || c.transaction_date || '-',
      description: c.transaction_summary || c.match_reason || '',
      confidence: c.confidence
    }))
    unmatchedTransactions.value = res.data.unmatched_transactions?.length || 0
    unmatchedInvoices.value = res.data.unmatched_invoices?.length || 0
    ElMessage.success('匹配完成')
  } catch (e) { ElMessage.error(e.response?.data?.detail || '匹配失败') }
  finally { matchLoading.value = false }
}

const confidencePillClass = (c) => c >= 0.9 ? 'pill--ok' : c >= 0.7 ? 'pill--warn' : 'pill--alert'

const fetchEnterprises = async () => {
  try {
    const res = await api.get('/api/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
  } catch (e) { ElMessage.error('加载企业列表失败') }
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page { width: 100%; margin-bottom: 32px; }

/* Segmented Control */
.seg-wrap { display: flex; margin-bottom: 24px; }
.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 999px;
  overflow: hidden;
}
.seg button {
  padding: 0 14px;
  height: 36px;
  background: transparent;
  border: none;
  font-size: 13px;
  color: var(--ink-2);
  cursor: pointer;
  transition: all .18s;
}
.seg button.on {
  background: var(--ink);
  color: var(--bg);
}
.seg button:hover:not(.on) {
  background: var(--panel);
}
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

/* Upload row */
.upload-row {
  display: grid;
  grid-template-columns: 200px 1fr auto;
  gap: 16px;
  align-items: end;
}
.upload-section { display: flex; flex-direction: column; gap: 6px; }
.upload-label { font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--mute); font-weight: 500; }
.enterprise-select { width: 100%; cursor: pointer; }

.section-divider { border-top: 1px solid var(--line); margin: 16px 0; }

.upload-dropzone {
  position: relative;
  border: 1px dashed var(--line);
  border-radius: 10px;
  background: repeating-linear-gradient(45deg, transparent 0 12px, rgba(41,38,27,.025) 12px 13px);
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: border-color .18s;
}
.upload-dropzone:hover,
.upload-dropzone.dragging { border-color: var(--accent); }
.dropzone-icon {
  width: 72px;
  height: 72px;
  border: 1px solid var(--line);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--mute);
  font-size: 28px;
  margin-bottom: 4px;
}
.dropzone-main { font-size: 13px; color: var(--ink-2); font-weight: 500; }
.dropzone-sub { font-size: 12px; color: var(--mute); }
.file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  width: 100%;
  height: 100%;
}

.upload-actions { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; justify-content: flex-end; }
.file-name { font-size: 12px; color: var(--mute); word-break: break-all; max-width: 160px; }

.upload-meta { font-size: 12px; color: var(--mute); margin-top: 8px; }

/* Result blocks */
.result-count {
  font-size: 13px;
  color: var(--ink-2);
  margin-bottom: 12px;
}
.result-block { margin-top: 24px; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 48px;
  color: var(--mute);
}
.empty-icon { font-size: 40px; opacity: 0.4; }
.empty-text { font-size: 13px; }

/* Parse section */
.parse-section { margin-top: 20px; }
.parse-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.parse-actions { display: flex; gap: 8px; }

/* Match summary */
.match-summary {
  font-size: 12px;
  color: var(--mute);
  margin-top: 8px;
}
</style>
