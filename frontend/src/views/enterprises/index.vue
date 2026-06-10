<template>
  <div class="page">
    <!-- Editorial Header -->
    <div class="page-header">
      <div class="header-left">
        <div class="page-eyebrow">§ 02 · ENTERPRISE LEDGER —</div>
        <h1 class="page-title">企业名册</h1>
        <p class="page-desc">管理已经接入的企业财税与融资档案。</p>
      </div>
      <div class="header-actions">
        <button v-if="showDevImport" class="btn secondary" :disabled="importingDirectory" @click="importDirectoryData">
          导入测试数据
        </button>
        <button class="btn primary" @click="showAddDialog = true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新增企业
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <div class="filter-input-wrap">
        <svg class="filter-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input
          v-model="searchKeyword"
          class="input"
          placeholder="搜索企业名称..."
          style="padding-left: 28px;"
          clearable
          @keyup.enter="fetchEnterprises"
        />
      </div>
      <div class="filter-group">
        <span class="filter-group-label">状态</span>
        <div class="seg small">
          <button :class="{ on: filterStatus === '' }" @click="filterStatus = ''; fetchEnterprises()">全部</button>
          <button :class="{ on: filterStatus === 'ACTIVE' }" @click="filterStatus = 'ACTIVE'; fetchEnterprises()">正常</button>
          <button :class="{ on: filterStatus === 'SUSPENDED' }" @click="filterStatus = 'SUSPENDED'; fetchEnterprises()">暂停</button>
          <button :class="{ on: filterStatus === 'CANCELLED' }" @click="filterStatus = 'CANCELLED'; fetchEnterprises()">注销</button>
        </div>
      </div>
      <div class="filter-group">
        <span class="filter-group-label">来源</span>
        <div class="seg small">
          <button :class="{ on: filterSource === '' }" @click="filterSource = ''; fetchEnterprises()">全部</button>
          <button :class="{ on: filterSource === 'DIRECT' }" @click="filterSource = 'DIRECT'; fetchEnterprises()">自主获客</button>
          <button :class="{ on: filterSource === 'CHANNEL' }" @click="filterSource = 'CHANNEL'; fetchEnterprises()">渠道推广</button>
          <button :class="{ on: filterSource === 'REFERRAL' }" @click="filterSource = 'REFERRAL'; fetchEnterprises()">老客推荐</button>
        </div>
      </div>
    </div>

    <!-- Table -->
    <div class="panel" style="padding: 0;">
      <table class="table" style="border-radius: 14px; overflow: hidden;">
        <thead>
          <tr>
            <th>企业名称</th>
            <th>行业</th>
            <th>状态</th>
            <th>来源</th>
            <th>融资评分</th>
            <th>最近分析</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in enterprises" :key="row.id" class="table-row" @click="viewDetail(row)">
            <td>
              <div class="enterprise-name-cell">
                <div class="ent-avatar">{{ row.name.charAt(0) }}</div>
                <span class="ent-name">{{ row.name }}</span>
              </div>
            </td>
            <td style="color: var(--ink-2);">{{ row.industry || '—' }}</td>
            <td>
              <span class="pill" :class="statusPillClass(row.status)">
                {{ statusLabel(row.status) }}
              </span>
            </td>
            <td>
              <span class="pill pill--idle" style="font-size: 11px;">
                {{ sourceLabel(row.source) }}
              </span>
            </td>
            <td>
              <span v-if="row.financing_score != null" class="score-val" :class="scoreClass(row.financing_score)">
                {{ row.financing_score }}
              </span>
              <span v-else style="color: var(--mute);">—</span>
            </td>
            <td>
              <span class="mono" style="font-size: 12px; color: var(--mute);">{{ row.last_analysis_date || '—' }}</span>
            </td>
            <td style="text-align: right;">
              <button class="btn ghost" style="height: 28px; padding: 0 4px; font-size: 12px;" @click.stop="viewDetail(row)">详情</button>
            </td>
          </tr>
          <tr v-if="enterprises.length === 0 && !loading">
            <td colspan="7" style="text-align: center; color: var(--mute); padding: 40px;">暂无企业数据</td>
          </tr>
        </tbody>
      </table>

      <div class="table-footer">
        <span class="table-count">共 {{ total }} 家企业</span>
        <div class="pager-wrap">
          <button class="btn secondary" style="height: 34px; padding: 0 14px; font-size: 12px;" :disabled="page <= 1" @click="page--; fetchEnterprises()">上一页</button>
          <span class="mono" style="font-size: 12px; color: var(--mute);">{{ page }} / {{ Math.ceil(total / pageSize) || 1 }}</span>
          <button class="btn secondary" style="height: 34px; padding: 0 14px; font-size: 12px;" :disabled="page >= Math.ceil(total / pageSize)" @click="page++; fetchEnterprises()">下一页</button>
        </div>
      </div>
    </div>

    <!-- Add Dialog -->
    <el-dialog v-model="showAddDialog" title="新增企业" width="520px" :close-on-click-modal="false" style="border-radius: 8px;">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="110px" class="add-form">
        <el-form-item label="企业名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入企业名称" />
        </el-form-item>
        <el-form-item label="纳税人识别号" prop="taxId">
          <el-input v-model="form.taxId" placeholder="统一社会信用代码" />
        </el-form-item>
        <el-form-item label="纳税人类型" prop="taxpayerType">
          <el-select v-model="form.taxpayerType" placeholder="请选择" style="width: 100%">
            <el-option label="一般纳税人" value="GENERAL" />
            <el-option label="小规模纳税人" value="SMALL" />
          </el-select>
        </el-form-item>
        <el-form-item label="行业" prop="industry">
          <el-input v-model="form.industry" placeholder="如：软件开发、咨询服务" />
        </el-form-item>
        <el-form-item label="注册地" prop="location">
          <el-input v-model="form.location" placeholder="如：江苏省南京市" />
        </el-form-item>
        <el-form-item label="来源" prop="source">
          <el-select v-model="form.source" placeholder="请选择" style="width: 100%">
            <el-option label="自主获客" value="DIRECT" />
            <el-option label="渠道推广" value="CHANNEL" />
            <el-option label="老客推荐" value="REFERRAL" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false" style="border-radius: 999px;">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd" style="border-radius: 999px;">确定</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api'

const router = useRouter()
const enterprises = ref([])
const loading = ref(false)
const showAddDialog = ref(false)
const submitting = ref(false)
const importingDirectory = ref(false)
const formRef = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchKeyword = ref('')
const filterStatus = ref('')
const filterSource = ref('')
const showDevImport = computed(() => import.meta.env.DEV)

const form = reactive({
  name: '', taxId: '', taxpayerType: '', industry: '', location: '', source: ''
})

const formRules = {
  name: [{ required: true, message: '请输入企业名称', trigger: 'blur' }],
  taxId: [{ required: true, message: '请输入纳税人识别号', trigger: 'blur' }],
  taxpayerType: [{ required: true, message: '请选择纳税人类型', trigger: 'change' }],
  source: [{ required: true, message: '请选择来源', trigger: 'change' }]
}

const statusLabel = (s) => ({ ACTIVE: '正常', SUSPENDED: '暂停', CANCELLED: '注销' }[s] || s)
const sourceLabel = (s) => ({ DIRECT: '自主获客', CHANNEL: '渠道推广', REFERRAL: '老客推荐' }[s] || s)
const statusPillClass = (s) => ({ ACTIVE: 'pill--ok', SUSPENDED: 'pill--warn', CANCELLED: 'pill--idle' }[s] || 'pill--idle')
const scoreClass = (score) => score >= 70 ? 'score-high' : score >= 50 ? 'score-mid' : 'score-low'

const fetchEnterprises = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value, sort_by: 'created_at', sort_order: 'desc' }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterSource.value) params.source = filterSource.value
    const res = await api.get('/enterprises', { params })
    enterprises.value = res.data.items
    total.value = res.data.total
  } catch { ElMessage.error('加载企业列表失败') }
  finally { loading.value = false }
}

const submitAdd = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    await api.post('/enterprises', {
      name: form.name, tax_number: form.taxId, taxpayer_type: form.taxpayerType,
      industry: form.industry || null, province: form.location || null, source: form.source
    })
    ElMessage.success('企业添加成功')
    showAddDialog.value = false
    Object.keys(form).forEach(k => form[k] = '')
    fetchEnterprises()
  } catch (e) { ElMessage.error(e.response?.data?.detail || '添加失败') }
  finally { submitting.value = false }
}

const importDirectoryData = async () => {
  importingDirectory.value = true
  try {
    const res = await api.post('/import/enterprises/from_directory', {
      directory_path: '/Volumes/共享文件夹/财务项目/银行流水',
      taxpayer_type: 'SMALL',
      source: 'DIRECT',
      import_bank_statements: true,
      import_invoice_details: true
    })
    const data = res.data
    ElMessage.success(`导入完成：新增 ${data.enterprises_created} 家，流水 ${data.transactions_imported} 笔，进销项 ${data.invoice_rows_imported || 0} 行`)
    fetchEnterprises()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导入测试数据失败')
  } finally {
    importingDirectory.value = false
  }
}

const viewDetail = async (row) => {
  router.push({ path: `/enterprises/${row.id}` })
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page { width: 100%; }

/* Editorial Header */
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
.header-actions { flex-shrink: 0; display: flex; gap: 10px; }

/* Filters */
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: center;
  flex-wrap: wrap;
}
.filter-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  width: 240px;
}
.filter-icon {
  position: absolute;
  left: 0;
  color: var(--mute);
  pointer-events: none;
  z-index: 1;
}
.filter-group-label {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--mute);
  font-weight: 500;
}

/* Table */
.table thead th {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
  font-weight: 400;
  padding: 14px 16px;
}
.table-row { cursor: pointer; }

.enterprise-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ent-avatar {
  width: 32px;
  height: 32px;
  border-radius: 4px;
  background: var(--panel);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  flex-shrink: 0;
}
.ent-name {
  font-weight: 500;
  color: var(--ink);
  font-size: 13.5px;
}

/* Score badge (still using colored badge since pill is for status) */
.score-val {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 22px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
}
.score-high { background: var(--ok-bg); color: var(--ok-fg); }
.score-mid  { background: var(--warn-bg); color: var(--warn-fg); }
.score-low  { background: var(--alert-bg); color: var(--alert-fg); }

.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-top: 1px solid var(--line-soft);
}
.table-count { font-size: 13px; color: var(--mute); }
.pager-wrap { display: flex; align-items: center; gap: 10px; }

.add-form :deep(.el-form-item__label) {
  font-weight: 600;
  font-size: 13px;
}

.detail-dialog :deep(.el-dialog) {
  border-radius: 10px;
  background: var(--bg);
}
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}
.detail-title {
  margin: 0;
  color: var(--ink);
  font-size: 28px;
  line-height: 1.2;
  font-weight: 600;
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
.finance-kpi {
  background: var(--panel);
  border-radius: 8px;
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
  background: var(--panel);
  border-radius: 8px;
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
.detail-loading {
  padding: 20px;
}
</style>
