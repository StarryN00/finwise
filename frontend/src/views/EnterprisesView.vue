<template>
  <div class="dashboard">
    <!-- Header -->
    <header class="dashboard-header">
      <div class="header-left">
        <span class="logo-icon">💰</span>
        <span class="logo-text">智税管家</span>
      </div>
      <div class="header-right">
        <el-dropdown @command="handleCommand">
          <span class="user-info">
            <el-icon><User /></el-icon>
            <span>{{ authStore.user?.real_name || authStore.user?.username }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- Main Content -->
    <div class="dashboard-content">
      <!-- Sidebar -->
      <aside class="sidebar">
        <el-menu
          :default-active="activeMenu"
          class="sidebar-menu"
          @select="handleMenuSelect"
        >
          <el-menu-item index="dashboard">
            <el-icon><DataLine /></el-icon>
            <span>企业总览</span>
          </el-menu-item>
          <el-menu-item index="enterprises">
            <el-icon><OfficeBuilding /></el-icon>
            <span>企业管理</span>
          </el-menu-item>
          <el-menu-item index="import">
            <el-icon><Upload /></el-icon>
            <span>数据导入</span>
          </el-menu-item>
          <el-menu-item index="reports">
            <el-icon><Document /></el-icon>
            <span>报告管理</span>
          </el-menu-item>
        </el-menu>
      </aside>

      <!-- Main Panel -->
      <main class="main-panel">
        <div class="page-header">
          <h1 class="page-title">企业管理</h1>
          <el-button type="primary" @click="showAddDialog">
            <el-icon><Plus /></el-icon>
            添加企业
          </el-button>
        </div>

        <!-- Search & Filter -->
        <div class="filter-bar">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索企业名称..."
            clearable
            style="width: 300px;"
            @clear="fetchEnterprises"
            @keyup.enter="fetchEnterprises"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px;" @change="fetchEnterprises">
            <el-option label="活跃" value="ACTIVE" />
            <el-option label="非活跃" value="INACTIVE" />
          </el-select>
          <el-select v-model="filterSource" placeholder="来源" clearable style="width: 120px;" @change="fetchEnterprises">
            <el-option label="直拓" value="DIRECT" />
            <el-option label="刘总介绍" value="LIU" />
            <el-option label="平总介绍" value="PING" />
          </el-select>
        </div>

        <!-- Enterprises Table -->
        <div class="table-card">
          <el-table :data="enterprises" v-loading="loading" stripe style="width: 100%">
            <el-table-column prop="name" label="企业名称" min-width="200" />
            <el-table-column prop="industry" label="行业" width="120">
              <template #default="{ row }">
                {{ row.industry || '--' }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">
                  {{ row.status === 'ACTIVE' ? '活跃' : '非活跃' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="100">
              <template #default="{ row }">
                <span class="source-tag">{{ getSourceLabel(row.source) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="financing_score" label="融资评分" width="100">
              <template #default="{ row }">
                <span v-if="row.financing_score" :class="getScoreClass(row.financing_score)">
                  {{ row.financing_score }}
                </span>
                <span v-else class="no-score">--</span>
              </template>
            </el-table-column>
            <el-table-column prop="last_analysis_date" label="最近分析" width="120">
              <template #default="{ row }">
                {{ row.last_analysis_date || '--' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="viewDetail(row)">查看</el-button>
                <el-button type="primary" link size="small" @click="editEnterprise(row)">编辑</el-button>
                <el-button type="danger" link size="small" @click="deleteEnterprise(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- Pagination -->
          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :total="total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="fetchEnterprises"
              @size-change="fetchEnterprises"
            />
          </div>
        </div>
      </main>
    </div>

    <!-- Add/Edit Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'add' ? '添加企业' : '编辑企业'"
      width="500px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="企业名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入企业名称" />
        </el-form-item>
        <el-form-item label="税号" prop="tax_number">
          <el-input v-model="form.tax_number" placeholder="请输入税号" />
        </el-form-item>
        <el-form-item label="行业" prop="industry">
          <el-input v-model="form.industry" placeholder="请输入行业" />
        </el-form-item>
        <el-form-item label="纳税人类型" prop="taxpayer_type">
          <el-select v-model="form.taxpayer_type" style="width: 100%;">
            <el-option label="一般纳税人" value="GENERAL" />
            <el-option label="小规模纳税人" value="SMALL" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源" prop="source">
          <el-select v-model="form.source" style="width: 100%;">
            <el-option label="直拓" value="DIRECT" />
            <el-option label="刘总介绍" value="LIU" />
            <el-option label="平总介绍" value="PING" />
          </el-select>
        </el-form-item>
        <el-form-item label="省份" prop="province">
          <el-input v-model="form.province" placeholder="请输入省份" />
        </el-form-item>
        <el-form-item label="城市" prop="city">
          <el-input v-model="form.city" placeholder="请输入城市" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const router = useRouter()
const authStore = useAuthStore()

const activeMenu = ref('enterprises')

const searchKeyword = ref('')
const filterStatus = ref('')
const filterSource = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const enterprises = ref([])

const dialogVisible = ref(false)
const dialogMode = ref('add')
const formRef = ref(null)
const editingId = ref(null)

const form = reactive({
  name: '',
  tax_number: '',
  taxpayer_type: 'SMALL',
  industry: '',
  source: 'DIRECT',
  province: '',
  city: ''
})

const rules = {
  name: [{ required: true, message: '请输入企业名称', trigger: 'blur' }]
}

const getSourceLabel = (source) => {
  const map = { 'DIRECT': '直拓', 'LIU': '刘总', 'PING': '平总' }
  return map[source] || source || '--'
}

const getScoreClass = (score) => {
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-medium'
  return 'score-low'
}

const handleCommand = (command) => {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}

const handleMenuSelect = (index) => {
  activeMenu.value = index
  if (index === 'dashboard') {
    router.push('/')
  } else if (index === 'enterprises') {
    router.push('/enterprises')
  }
}

const fetchEnterprises = async () => {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterSource.value) params.source = filterSource.value

    const response = await api.get('/enterprises', { params })
    enterprises.value = response.data.items
    total.value = response.data.total
  } catch (error) {
    console.error('Failed to fetch enterprises:', error)
  } finally {
    loading.value = false
  }
}

const showAddDialog = () => {
  dialogMode.value = 'add'
  Object.assign(form, {
    name: '',
    tax_number: '',
    taxpayer_type: 'SMALL',
    industry: '',
    source: 'DIRECT',
    province: '',
    city: ''
  })
  editingId.value = null
  dialogVisible.value = true
}

const editEnterprise = (row) => {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    tax_number: row.tax_number || '',
    taxpayer_type: row.taxpayer_type || 'SMALL',
    industry: row.industry || '',
    source: row.source || 'DIRECT',
    province: row.province || '',
    city: row.city || ''
  })
  dialogVisible.value = true
}

const submitForm = async () => {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
    if (dialogMode.value === 'add') {
      await api.post('/enterprises', form)
      ElMessage.success('添加成功')
    } else {
      await api.put(`/enterprises/${editingId.value}`, form)
      ElMessage.success('更新成功')
    }
    dialogVisible.value = false
    fetchEnterprises()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  }
}

const viewDetail = (row) => {
  router.push(`/enterprise/${row.id}`)
}

const deleteEnterprise = async (row) => {
  try {
    await ElMessageBox.confirm(`确定要删除企业 "${row.name}" 吗？`, '提示', {
      type: 'warning'
    })
    await api.delete(`/enterprises/${row.id}`)
    ElMessage.success('删除成功')
    fetchEnterprises()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

onMounted(() => {
  fetchEnterprises()
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: #f5f7fa;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 24px;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-icon {
  font-size: 28px;
}

.logo-text {
  font-size: 20px;
  font-weight: 600;
  color: #333;
}

.header-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 4px;
}

.user-info:hover {
  background-color: #f5f7fa;
}

.dashboard-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.sidebar {
  width: 200px;
  background: white;
  border-right: 1px solid #e8e8e8;
  padding-top: 16px;
}

.sidebar-menu {
  border-right: none;
}

.main-panel {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: #333;
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.table-card {
  padding: 20px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

.source-tag {
  font-size: 12px;
  padding: 2px 8px;
  background: #f0f2f5;
  border-radius: 4px;
  color: #666;
}

.score-high {
  color: #67c23a;
  font-weight: 600;
}

.score-medium {
  color: #e6a23c;
  font-weight: 600;
}

.score-low {
  color: #909399;
}

.no-score {
  color: #c0c4cc;
}
</style>
