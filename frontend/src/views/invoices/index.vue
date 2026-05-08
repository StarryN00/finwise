<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <span style="font-size: 16px; font-weight: 600">发票管理</span>
      </template>
      <el-tabs v-model="activeTab" class="invoice-tabs">
        <!-- 发票管理 Tab -->
        <el-tab-pane label="发票管理" name="invoices">
          <div class="tab-content">
            <div class="upload-section">
              <el-form :inline="true" style="width: 100%">
                <el-form-item label="选择企业" style="margin-right: 16px">
                  <el-select v-model="invoiceEnterpriseId" placeholder="请先选择企业" style="width: 260px" filterable>
                    <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
                  </el-select>
                </el-form-item>
              </el-form>
              <el-upload
                ref="invoiceUploadRef"
                :auto-upload="false"
                :limit="1"
                :on-change="onInvoiceFileChange"
                :file-list="invoiceFileList"
                accept=".xls,.xlsx,.csv"
                style="width: 100%"
              >
                <template #trigger>
                  <el-button type="default">
                    <el-icon><Upload /></el-icon>
                    选择 Excel 文件
                  </el-button>
                </template>
                <el-button type="primary" style="margin-left: 12px" :loading="invoiceUploading" :disabled="!invoiceFile || !invoiceEnterpriseId" @click="submitInvoiceImport">
                  导入发票
                </el-button>
                <template #tip>
                  <div class="upload-tip">支持 .xls、.xlsx、.csv 格式，文件不超过 10MB</div>
                </template>
              </el-upload>
            </div>

            <el-divider />

            <!-- 发票列表 -->
            <div v-if="invoiceList.length > 0">
              <div style="margin-bottom: 12px; color: #666">共 {{ invoiceList.length }} 条发票记录</div>
              <el-table :data="invoiceList" stripe size="small" max-height="400">
                <el-table-column prop="invoiceNumber" label="发票号码" width="150" />
                <el-table-column prop="date" label="开票日期" width="110" />
                <el-table-column prop="amount" label="金额（含税）" width="130" align="right">
                  <template #default="{ row }">¥{{ Number(row.amount).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="taxAmount" label="税额" width="110" align="right">
                  <template #default="{ row }">¥{{ Number(row.taxAmount || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="type" label="类型" width="80">
                  <template #default="{ row }">
                    <el-tag :type="row.type === 'SALES' ? 'success' : 'warning'" size="small">
                      {{ row.type === 'SALES' ? '销项' : '进项' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态" width="90">
                  <template #default="{ row }">
                    <el-tag :type="row.status === 'VALID' ? 'success' : 'info'" size="small">
                      {{ row.status === 'VALID' ? '有效' : '作废' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            <el-empty v-else description="暂无发票数据，请先上传导入" />
          </div>
        </el-tab-pane>

        <!-- 银行流水 Tab -->
        <el-tab-pane label="银行流水" name="bank">
          <div class="tab-content">
            <div class="upload-section">
              <el-form :inline="true" style="width: 100%">
                <el-form-item label="选择企业" style="margin-right: 16px">
                  <el-select v-model="bankEnterpriseId" placeholder="请先选择企业" style="width: 260px" filterable>
                    <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
                  </el-select>
                </el-form-item>
              </el-form>
              <el-upload
                ref="bankUploadRef"
                :auto-upload="false"
                :limit="1"
                :on-change="onBankFileChange"
                :file-list="bankFileList"
                accept=".xls,.xlsx,.csv"
                style="width: 100%"
              >
                <template #trigger>
                  <el-button type="default">
                    <el-icon><Upload /></el-icon>
                    选择银行流水 Excel
                  </el-button>
                </template>
                <el-button type="primary" style="margin-left: 12px" :loading="bankUploading" :disabled="!bankFile || !bankEnterpriseId" @click="submitBankImport">
                  上传
                </el-button>
                <template #tip>
                  <div class="upload-tip">支持 .xls、.xlsx、.csv 格式</div>
                </template>
              </el-upload>
            </div>

            <!-- AI 解析 & 匹配 -->
            <div v-if="importBatchId" style="margin-top: 20px">
              <el-alert v-if="parseStatus === 'PENDING'" type="info" :closable="false" show-icon>
                流水已上传，正在等待 AI 解析...
              </el-alert>
              <el-alert v-if="parseStatus === 'PROCESSING'" type="warning" :closable="false" show-icon>
                AI 正在解析银行流水，请稍候...
              </el-alert>
              <el-alert v-if="parseStatus === 'COMPLETED'" type="success" :closable="false" show-icon>
                解析完成，共识别 {{ parsedTransactions.length }} 笔流水
              </el-alert>

              <div v-if="importBatchId" style="margin-top: 16px">
                <el-button type="default" size="small" :loading="parseLoading" :disabled="parseStatus === 'PROCESSING'" @click="runAiParse">
                  {{ parseStatus === 'PENDING' ? '开始 AI 解析' : '重新解析' }}
                </el-button>
                <el-button type="success" size="small" :loading="matchLoading" :disabled="parseStatus !== 'COMPLETED'" @click="runMatch">
                  发票匹配
                </el-button>
              </div>
            </div>

            <!-- 流水列表 -->
            <div v-if="parsedTransactions.length > 0" style="margin-top: 20px">
              <div style="margin-bottom: 12px; color: #666">识别流水 {{ parsedTransactions.length }} 笔</div>
              <el-table :data="parsedTransactions" stripe size="small" max-height="300">
                <el-table-column prop="date" label="交易日期" width="120" />
                <el-table-column prop="description" label="摘要" min-width="200" show-overflow-tooltip />
                <el-table-column prop="amount" label="金额" width="130" align="right">
                  <template #default="{ row }">¥{{ Number(row.amount).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="balance" label="余额" width="130" align="right">
                  <template #default="{ row }">¥{{ Number(row.balance || 0).toLocaleString() }}</template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 匹配结果 -->
            <div v-if="matchResults.length > 0" style="margin-top: 20px">
              <div style="margin-bottom: 12px; color: #666; font-weight: 600">匹配结果</div>
              <el-table :data="matchResults" stripe size="small">
                <el-table-column label="发票号" prop="invoiceNumber" width="150" />
                <el-table-column label="金额" width="130" align="right">
                  <template #default="{ row }">¥{{ Number(row.amount).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column label="交易日期" prop="date" width="120" />
                <el-table-column label="摘要" prop="description" min-width="180" show-overflow-tooltip />
                <el-table-column label="匹配置信度" width="110">
                  <template #default="{ row }">
                    <el-tag :type="row.confidence >= 0.9 ? 'success' : row.confidence >= 0.7 ? 'warning' : 'info'" size="small">
                      {{ (row.confidence * 100).toFixed(0) }}%
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
              <div style="color: #999; font-size: 12px; margin-top: 8px">
                未匹配流水：{{ unmatchedTransactions }} 笔　未匹配发票：{{ unmatchedInvoices }} 笔
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import api from '@/api'

const activeTab = ref('invoices')

// 企业列表
const enterprises = ref([])
const invoiceEnterpriseId = ref('')
const bankEnterpriseId = ref('')

// 发票导入
const invoiceUploadRef = ref(null)
const invoiceFile = ref(null)
const invoiceFileList = ref([])
const invoiceUploading = ref(false)
const invoiceList = ref([])

const onInvoiceFileChange = (file) => {
  invoiceFile.value = file.raw
  invoiceFileList.value = [file]
}

const submitInvoiceImport = async () => {
  if (!invoiceFile.value) return
  invoiceUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', invoiceFile.value)
    const res = await api.post(`/import/invoices?enterprise_id=${invoiceEnterpriseId.value}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success(`发票导入成功，共 ${res.data.total_rows} 条`)
    invoiceList.value = res.data.invoices || []
    invoiceUploadRef.value?.clearFiles()
    invoiceFile.value = null
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '发票导入失败')
  } finally {
    invoiceUploading.value = false
  }
}

// 银行流水
const bankUploadRef = ref(null)
const bankFile = ref(null)
const bankFileList = ref([])
const bankUploading = ref(false)
const importBatchId = ref('')
const parseStatus = ref('PENDING')
const parseLoading = ref(false)
const matchLoading = ref(false)
const parsedTransactions = ref([])
const matchResults = ref([])
const unmatchedTransactions = ref(0)
const unmatchedInvoices = ref(0)

const onBankFileChange = (file) => {
  bankFile.value = file.raw
  bankFileList.value = [file]
}

const submitBankImport = async () => {
  if (!bankFile.value) return
  bankUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', bankFile.value)
    const res = await api.post(`/import/bank_statements?enterprise_id=${bankEnterpriseId.value}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    importBatchId.value = res.data.batch_id
    parseStatus.value = 'PENDING'
    parsedTransactions.value = []
    matchResults.value = []
    ElMessage.success('银行流水上传成功，可点击"开始 AI 解析"')
    bankUploadRef.value?.clearFiles()
    bankFile.value = null
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  } finally {
    bankUploading.value = false
  }
}

const runAiParse = async () => {
  if (!importBatchId.value || !bankEnterpriseId.value) return
  parseLoading.value = true
  parseStatus.value = 'PROCESSING'
  try {
    await api.post('/parse/bank_statement', {
      enterprise_id: bankEnterpriseId.value,
      file_id: importBatchId.value
    })
    parseStatus.value = 'COMPLETED'
    // Fetch parsed transactions (in real app would refetch from store; here just show status)
    ElMessage.success('AI 解析完成')
  } catch (e) {
    parseStatus.value = 'PENDING'
    ElMessage.error(e.response?.data?.detail || 'AI 解析失败')
  } finally {
    parseLoading.value = false
  }
}

const runMatch = async () => {
  if (!bankEnterpriseId.value) return
  matchLoading.value = true
  try {
    const res = await api.post('/parse/match', {
      enterprise_id: bankEnterpriseId.value
    })
    matchResults.value = (res.data.candidates || []).map(c => ({
      invoiceNumber: `INV-${c.invoice_index}`,
      amount: 0,
      date: '-',
      description: c.match_reason,
      confidence: c.confidence
    }))
    unmatchedTransactions.value = res.data.unmatched_transactions?.length || 0
    unmatchedInvoices.value = res.data.unmatched_invoices?.length || 0
    ElMessage.success('匹配完成')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '匹配失败')
  } finally {
    matchLoading.value = false
  }
}

const fetchEnterprises = async () => {
  try {
    const res = await api.get('/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
  } catch (e) {
    // silent
  }
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page-container { width: 100%; }
.tab-content { padding-top: 12px; }
.upload-section { padding: 12px 0; }
.upload-tip { margin-top: 8px; color: #999; font-size: 12px; }
</style>
