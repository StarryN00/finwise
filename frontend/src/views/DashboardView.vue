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
        <h1 class="page-title">企业总览</h1>

        <!-- Stats Cards -->
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-icon" style="background: #e8f4fd;">
              <el-icon :size="28" color="#409eff"><OfficeBuilding /></el-icon>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.total }}</span>
              <span class="stat-label">企业总数</span>
            </div>
          </div>

          <div class="stat-card">
            <div class="stat-icon" style="background: #e8faf0;">
              <el-icon :size="28" color="#67c23a"><CircleCheck /></el-icon>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.active }}</span>
              <span class="stat-label">活跃企业</span>
            </div>
          </div>

          <div class="stat-card">
            <div class="stat-icon" style="background: #fef0e8;">
              <el-icon :size="28" color="#e6a23c"><Star /></el-icon>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.highPotential }}</span>
              <span class="stat-label">高潜力企业</span>
            </div>
          </div>

          <div class="stat-card">
            <div class="stat-icon" style="background: #fde8e8;">
              <el-icon :size="28" color="#f56c6c"><Warning /></el-icon>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.pendingAnalysis }}</span>
              <span class="stat-label">待分析企业</span>
            </div>
          </div>
        </div>

        <!-- Charts Row -->
        <div class="charts-row">
          <!-- Enterprise Source Distribution -->
          <div class="chart-card">
            <h3 class="chart-title">企业来源分布</h3>
            <div ref="sourceChartRef" class="chart-container"></div>
          </div>

          <!-- Industry Distribution -->
          <div class="chart-card">
            <h3 class="chart-title">行业分布</h3>
            <div ref="industryChartRef" class="chart-container"></div>
          </div>
        </div>

        <!-- Recent Enterprises Table -->
        <div class="table-card">
          <h3 class="chart-title">最近添加的企业</h3>
          <el-table :data="recentEnterprises" stripe style="width: 100%">
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
          </el-table>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import * as echarts from 'echarts'
import api from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const activeMenu = ref('dashboard')
const sourceChartRef = ref(null)
const industryChartRef = ref(null)
let sourceChart = null
let industryChart = null

const stats = reactive({
  total: 0,
  active: 0,
  highPotential: 0,
  pendingAnalysis: 0
})

const recentEnterprises = ref([])

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

const fetchDashboardData = async () => {
  try {
    const response = await api.get('/api/enterprises', { params: { page_size: 100 } })
    const data = response.data

    stats.total = data.total || 0
    stats.active = data.items.filter(e => e.status === 'ACTIVE').length
    stats.highPotential = data.items.filter(e => e.financing_score && e.financing_score >= 70).length
    stats.pendingAnalysis = data.items.filter(e => !e.financing_score).length

    recentEnterprises.value = data.items.slice(0, 10)

    updateSourceChart(data.items)
    updateIndustryChart(data.items)
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error)
  }
}

const updateSourceChart = (items) => {
  if (!sourceChartRef.value) return

  const sourceCount = {}
  items.forEach(item => {
    const source = item.source || 'UNKNOWN'
    sourceCount[source] = (sourceCount[source] || 0) + 1
  })

  const sourceMap = { 'DIRECT': '直拓', 'LIU': '刘总介绍', 'PING': '平总介绍' }

  const chartData = Object.entries(sourceCount).map(([key, value]) => ({
    name: sourceMap[key] || key,
    value
  }))

  if (!sourceChart) {
    sourceChart = echarts.init(sourceChartRef.value)
  }

  sourceChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'middle' },
    series: [{
      type: 'pie',
      radius: ['45%', '75%'],
      center: ['60%', '50%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      emphasis: {
        label: { show: true, fontSize: 14, fontWeight: 'bold' }
      },
      data: chartData.length ? chartData : [{ name: '暂无数据', value: 1 }]
    }],
    color: ['#667eea', '#764ba2', '#f6d365', '#fda085']
  })
}

const updateIndustryChart = (items) => {
  if (!industryChartRef.value) return

  const industryCount = {}
  items.forEach(item => {
    const industry = item.industry || '未知'
    industryCount[industry] = (industryCount[industry] || 0) + 1
  })

  const chartData = Object.entries(industryCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, value]) => ({ name, value }))

  if (!industryChart) {
    industryChart = echarts.init(industryChartRef.value)
  }

  industryChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: chartData.map(d => d.name),
      axisLabel: { interval: 0, fontSize: 11 }
    },
    series: [{
      type: 'bar',
      data: chartData.map(d => d.value),
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#667eea' },
          { offset: 1, color: '#764ba2' }
        ]),
        borderRadius: [0, 4, 4, 0]
      },
      barWidth: '50%'
    }]
  })
}

const handleResize = () => {
  sourceChart?.resize()
  industryChart?.resize()
}

onMounted(() => {
  fetchDashboardData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  sourceChart?.dispose()
  industryChart?.dispose()
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

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: #333;
  margin-bottom: 24px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 12px;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #333;
}

.stat-label {
  font-size: 14px;
  color: #666;
  margin-top: 4px;
}

.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.chart-card {
  padding: 20px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.chart-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 16px;
}

.chart-container {
  height: 260px;
}

.table-card {
  padding: 20px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
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