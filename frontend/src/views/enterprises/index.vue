<template>
  <div class="page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">企业管理</h1>
        <p class="page-desc">管理服务企业基本信息、纳税类型与融资状态</p>
      </div>
      <el-button type="primary" @click="showAddDialog = true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="margin-right:6px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新增企业
      </el-button>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索企业名称..."
        style="width: 240px"
        clearable
        @keyup.enter="fetchEnterprises"
        @clear="fetchEnterprises"
      >
        <template #prefix>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        </template>
      </el-input>
      <el-select v-model="filterStatus" placeholder="状态" style="width: 140px" clearable @change="fetchEnterprises">
        <el-option label="正常" value="ACTIVE" />
        <el-option label="暂停" value="SUSPENDED" />
        <el-option label="注销" value="CANCELLED" />
      </el-select>
      <el-select v-model="filterSource" placeholder="来源" style="width: 140px" clearable @change="fetchEnterprises">
        <el-option label="自主获客" value="DIRECT" />
        <el-option label="渠道推广" value="CHANNEL" />
        <el-option label="老客推荐" value="REFERRAL" />
      </el-select>
    </div>

    <!-- Table -->
    <div class="table-card">
      <el-table
        :data="enterprises"
        stripe
        style="width: 100%"
        v-loading="loading"
        @row-click="viewDetail"
      >
        <el-table-column prop="name" label="企业名称" min-width="180">
          <template #default="{ row }">
            <div class="enterprise-name-cell">
              <div class="ent-avatar">{{ row.name.charAt(0) }}</div>
              <span class="ent-name">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="industry" label="行业" width="120" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <span class="status-badge" :class="'status-' + row.status.toLowerCase()">
              {{ statusLabel(row.status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="100">
          <template #default="{ row }">
            <span class="source-tag">{{ sourceLabel(row.source) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="financing_score" label="融资评分" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.financing_score != null" class="score-badge" :class="'score-' + scoreClass(row.financing_score)">
              {{ row.financing_score }}
            </span>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_analysis_date" label="最近分析" width="130">
          <template #default="{ row }">
            <span class="mono text-muted" style="font-size:12px">{{ row.last_analysis_date || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click.stop="viewDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span class="table-count">共 {{ total }} 家企业</span>
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next"
          @size-change="fetchEnterprises"
          @current-change="fetchEnterprises"
        />
      </div>
    </div>

    <!-- Add Dialog -->
    <el-dialog v-model="showAddDialog" title="新增企业" width="520px" :close-on-click-modal="false">
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
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const enterprises = ref([])
const loading = ref(false)
const showAddDialog = ref(false)
const submitting = ref(false)
const formRef = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchKeyword = ref('')
const filterStatus = ref('')
const filterSource = ref('')

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
const scoreClass = (score) => score >= 70 ? 'high' : score >= 50 ? 'mid' : 'low'

const fetchEnterprises = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value, sort_by: 'created_at', sort_order: 'desc' }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterSource.value) params.source = filterSource.value
    const res = await api.get('/api/enterprises', { params })
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
    await api.post('/api/enterprises', {
      name: form.name, tax_id: form.taxId, taxpayer_type: form.taxpayerType,
      industry: form.industry || null, location: form.location || null, source: form.source
    })
    ElMessage.success('企业添加成功')
    showAddDialog.value = false
    Object.keys(form).forEach(k => form[k] = '')
    fetchEnterprises()
  } catch (e) { ElMessage.error(e.response?.data?.detail || '添加失败') }
  finally { submitting.value = false }
}

const viewDetail = (row) => ElMessage.info(`查看企业详情：${row.name}`)

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

.page-title {
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.page-desc {
  font-size: 13px;
  color: var(--color-text-muted);
}

.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: center;
}

.table-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-sm);
}

.enterprise-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ent-avatar {
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--color-accent-bg);
  color: var(--color-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.ent-name {
  font-weight: 600;
  color: var(--color-text-primary);
  font-size: 13px;
}

.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
}
.status-active { background: var(--color-success-light); color: var(--color-success); }
.status-suspended { background: var(--color-warning-light); color: var(--color-warning); }
.status-cancelled { background: var(--color-bg-alt); color: var(--color-text-muted); }

.source-tag {
  font-size: 12px;
  color: var(--color-text-muted);
}

.score-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 24px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 800;
}
.score-high { background: var(--color-success-light); color: var(--color-success); }
.score-mid { background: var(--color-warning-light); color: var(--color-warning); }
.score-low { background: var(--color-danger-light); color: var(--color-danger); }

.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}

.table-count {
  font-size: 13px;
  color: var(--color-text-muted);
}

.add-form :deep(.el-form-item__label) {
  font-weight: 600;
  font-size: 13px;
}
</style>