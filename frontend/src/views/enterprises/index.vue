<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>企业管理</span>
          <el-button type="primary" @click="showAddDialog = true">
            <el-icon><Plus /></el-icon>
            新增企业
          </el-button>
        </div>
      </template>

      <!-- 搜索筛选 -->
      <div class="filter-row">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索企业名称..."
          style="width: 240px; margin-right: 12px"
          clearable
          @keyup.enter="fetchEnterprises"
          @clear="fetchEnterprises"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filterStatus" placeholder="状态" style="width: 140px; margin-right: 12px" clearable @change="fetchEnterprises">
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

      <!-- 企业列表 -->
      <el-table :data=" enterprises" stripe style="width: 100%; margin-top: 16px" v-loading="loading">
        <el-table-column prop="name" label="企业名称" min-width="180" />
        <el-table-column prop="industry" label="行业" width="120" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="100">
          <template #default="{ row }">
            {{ sourceLabel(row.source) }}
          </template>
        </el-table-column>
        <el-table-column prop="financing_score" label="融资评分" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.financing_score != null" :class="'score-' + scoreClass(row.financing_score)">
              {{ row.financing_score }}
            </span>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_analysis_date" label="最近分析日期" width="130">
          <template #default="{ row }">
            {{ row.last_analysis_date || '--' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="viewDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        style="margin-top: 16px; justify-content: flex-end"
        @size-change="fetchEnterprises"
        @current-change="fetchEnterprises"
      />
    </el-card>

    <!-- 新增企业对话框 -->
    <el-dialog v-model="showAddDialog" title="新增企业" width="520px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="110px">
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
import { Plus, Search } from '@element-plus/icons-vue'
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
  name: '',
  taxId: '',
  taxpayerType: '',
  industry: '',
  location: '',
  source: ''
})

const formRules = {
  name: [{ required: true, message: '请输入企业名称', trigger: 'blur' }],
  taxId: [{ required: true, message: '请输入纳税人识别号', trigger: 'blur' }],
  taxpayerType: [{ required: true, message: '请选择纳税人类型', trigger: 'change' }],
  source: [{ required: true, message: '请选择来源', trigger: 'change' }]
}

const statusTagType = (status) => {
  const map = { ACTIVE: 'success', SUSPENDED: 'warning', CANCELLED: 'info' }
  return map[status] || ''
}

const statusLabel = (status) => {
  const map = { ACTIVE: '正常', SUSPENDED: '暂停', CANCELLED: '注销' }
  return map[status] || status
}

const sourceLabel = (source) => {
  const map = { DIRECT: '自主获客', CHANNEL: '渠道推广', REFERRAL: '老客推荐' }
  return map[source] || source
}

const scoreClass = (score) => {
  if (score >= 70) return 'high'
  if (score >= 50) return 'mid'
  return 'low'
}

const fetchEnterprises = async () => {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort_by: 'created_at',
      sort_order: 'desc'
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterSource.value) params.source = filterSource.value

    const res = await api.get('/api/enterprises', { params })
    enterprises.value = res.data.items
    total.value = res.data.total
  } catch (e) {
    ElMessage.error('加载企业列表失败')
  } finally {
    loading.value = false
  }
}

const submitAdd = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await api.post('/api/enterprises', {
      name: form.name,
      tax_id: form.taxId,
      taxpayer_type: form.taxpayerType,
      industry: form.industry || null,
      location: form.location || null,
      source: form.source
    })
    ElMessage.success('企业添加成功')
    showAddDialog.value = false
    Object.keys(form).forEach(k => form[k] = '')
    fetchEnterprises()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}

const viewDetail = (row) => {
  ElMessage.info(`查看企业详情：${row.name}`)
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page-container { width: 100%; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.filter-row { display: flex; align-items: center; }
.score-high { color: #67c23a; font-weight: bold; }
.score-mid { color: #e6a23c; font-weight: bold; }
.score-low { color: #f56c6c; font-weight: bold; }
.text-muted { color: #999; }
</style>
