<template>
  <section class="opening-workbench">
    <div class="opening-workbench__main">
      <p class="section-eyebrow">开账准备</p>
      <h2>{{ primaryGuidance.title }}</h2>
      <p>{{ primaryGuidance.description }}</p>
      <div class="opening-workbench__meta">
        <span>当前主体：{{ currentEnterpriseName }}</span>
        <span>当前期间：{{ workspace.currentPeriod }}</span>
      </div>
      <div class="opening-workbench__actions">
        <el-button type="primary" @click="goTo(primaryGuidance.primaryPath)">
          {{ primaryGuidance.primaryAction }}
        </el-button>
        <el-button v-if="primaryGuidance.secondaryAction" plain @click="goTo(primaryGuidance.secondaryPath)">
          {{ primaryGuidance.secondaryAction }}
        </el-button>
      </div>
    </div>

    <div class="onboarding-steps" aria-label="开账流程">
      <button
        v-for="step in onboardingSteps"
        :key="step.label"
        class="onboarding-step"
        :class="step.status"
        type="button"
        @click="goTo(step.path)"
      >
        <span class="onboarding-step__index">{{ step.index }}</span>
        <span>
          <strong>{{ step.label }}</strong>
          <small>{{ step.hint }}</small>
        </span>
      </button>
    </div>
  </section>

  <section class="metric-grid">
    <MetricCard
      v-for="metric in workspace.metrics"
      :key="metric.label"
      :label="metric.label"
      :value="metric.value"
      :subtext="metric.subtext"
      :tone="metric.tone"
    />
  </section>
  <el-alert v-if="workspace.loadError" type="error" :title="workspace.loadError" show-icon />

  <DataTableShell
    title="月度工作包"
    description="按企业跟踪导入、匹配、申报与报告状态"
    :action-label="packageActionLabel"
    @action="handlePackageAction"
  >
    <template #filters>
      <el-select v-model="statusFilter" placeholder="状态" style="width: 148px">
        <el-option label="全部状态" value="ALL" />
        <el-option label="待确认" value="PENDING_CONFIRMATION" />
        <el-option label="可导出" value="READY_TO_EXPORT" />
        <el-option label="数据不足" value="DATA_INSUFFICIENT" />
      </el-select>
    </template>
    <el-table v-if="filteredPackages.length" v-loading="workspace.isLoading" :data="filteredPackages" stripe>
      <el-table-column prop="company" label="企业名称" min-width="220" />
      <el-table-column prop="period" label="期间" width="110" />
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <StatusTag :status="row.status" />
        </template>
      </el-table-column>
      <el-table-column prop="pending" label="待确认" width="110" align="right" />
      <el-table-column prop="tax" label="预计增值税" width="140" align="right">
        <template #default="{ row }">
          <span class="amount">{{ row.tax }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else :description="hasEnterprises ? '暂无月度工作包' : '先创建第一家企业'">
      <el-button type="primary" @click="handlePackageAction">{{ packageActionLabel }}</el-button>
    </el-empty>
  </DataTableShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import DataTableShell from '../components/DataTableShell.vue'
import MetricCard from '../components/MetricCard.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const router = useRouter()
const statusFilter = ref('ALL')

const hasEnterprises = computed(() => workspace.enterprises.length > 0)
const hasPackages = computed(() => workspace.workPackages.length > 0)
const activePackage = computed(() => workspace.activePackage || workspace.workPackages[0])
const pendingCount = computed(() => Number(activePackage.value?.pending || 0))
const currentEnterpriseName = computed(() => workspace.activeOrganization || workspace.enterprises[0]?.name || '尚未建立企业')
const packageActionLabel = computed(() => (hasEnterprises.value ? '创建/查看工作包' : '创建企业档案'))

const primaryGuidance = computed(() => {
  if (!hasEnterprises.value) {
    return {
      title: '先创建第一家企业',
      description: '录入营业执照编号、行业、省市和基础信息后，再导入期初数据。',
      primaryAction: '创建企业档案',
      primaryPath: '/enterprises/init',
    }
  }

  if (!hasPackages.value) {
    return {
      title: '完成开账准备',
      description: '先导入期初报表或历史账套，再创建本月工作包。',
      primaryAction: '导入期初/历史账套',
      primaryPath: '/historical-import',
      secondaryAction: '创建月度工作包',
      secondaryPath: '/monthly-workspace',
    }
  }

  if (pendingCount.value > 0) {
    return {
      title: '处理当月凭证确认',
      description: '当月资料已进入处理流程，优先完成 AI 预处理后的凭证确认。',
      primaryAction: '进入凭证生成',
      primaryPath: '/vouchers',
      secondaryAction: '查看资金/发票台账',
      secondaryPath: '/bank-ledger',
    }
  }

  return {
    title: '生成申报与报告',
    description: '当月待确认事项已处理，继续检查账簿并输出申报、报表和健康报告。',
    primaryAction: '进入输出中心',
    primaryPath: '/output-center',
    secondaryAction: '查看账簿',
    secondaryPath: '/ledgers',
  }
})

const onboardingSteps = computed(() => [
  {
    index: 1,
    label: '第 1 步：建立企业档案',
    hint: hasEnterprises.value ? '已建立客户主体' : '营业执照编号必填',
    path: '/enterprises/init',
    status: hasEnterprises.value ? 'done' : 'active',
  },
  {
    index: 2,
    label: '第 2 步：导入期初/历史账套',
    hint: '利润表、资产负债表或历史账套',
    path: '/historical-import',
    status: hasEnterprises.value ? 'active' : 'pending',
  },
  {
    index: 3,
    label: '第 3 步：创建月度工作包',
    hint: hasPackages.value ? '已进入月度作业' : '选择企业和会计期间',
    path: '/monthly-workspace',
    status: hasPackages.value ? 'done' : hasEnterprises.value ? 'active' : 'pending',
  },
  {
    index: 4,
    label: '第 4 步：导入当月资料',
    hint: '银行流水、进项和销项发票',
    path: '/monthly-workspace',
    status: hasPackages.value ? 'active' : 'pending',
  },
  {
    index: 5,
    label: '第 5 步：AI预处理与凭证确认',
    hint: pendingCount.value > 0 ? `${pendingCount.value} 项待确认` : '匹配、补齐并确认凭证',
    path: '/vouchers',
    status: pendingCount.value > 0 ? 'active' : hasPackages.value ? 'done' : 'pending',
  },
  {
    index: 6,
    label: '第 6 步：输出申报与报告',
    hint: '申报表、账簿、健康报告',
    path: '/output-center',
    status: hasPackages.value && pendingCount.value === 0 ? 'active' : 'pending',
  },
])

const filteredPackages = computed(() => {
  if (statusFilter.value === 'ALL') {
    return workspace.workPackages
  }
  return workspace.workPackages.filter((item) => item.status === statusFilter.value)
})

function goTo(path) {
  router.push(path)
}

function handlePackageAction() {
  if (!hasEnterprises.value) {
    router.push('/enterprises/init')
    return
  }
  router.push('/monthly-workspace')
}
</script>

<style scoped>
.opening-workbench {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(360px, 1.4fr);
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-md);
  background: var(--fw-surface);
}

.opening-workbench__main h2 {
  margin: 4px 0 8px;
  color: var(--fw-ink);
  font-size: 22px;
}

.opening-workbench__main p {
  margin: 0;
  color: var(--fw-muted);
}

.section-eyebrow {
  margin: 0;
  color: var(--fw-brand);
  font-size: 12px;
  font-weight: 800;
}

.opening-workbench__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  color: var(--fw-muted);
  font-size: 12px;
}

.opening-workbench__meta span {
  padding: 4px 8px;
  border-radius: var(--fw-radius-sm);
  background: #f3f7fc;
}

.opening-workbench__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.onboarding-steps {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.onboarding-step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 72px;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: #ffffff;
  color: var(--fw-ink);
  text-align: left;
  cursor: pointer;
}

.onboarding-step:hover,
.onboarding-step.active {
  border-color: #93c5fd;
  background: #eff6ff;
}

.onboarding-step.done {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.onboarding-step.pending {
  color: #75849a;
}

.onboarding-step__index {
  display: grid;
  flex: 0 0 24px;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: #ffffff;
  background: var(--fw-brand);
  font-size: 12px;
  font-weight: 800;
}

.onboarding-step.pending .onboarding-step__index {
  background: #9aa8bb;
}

.onboarding-step strong,
.onboarding-step small {
  display: block;
}

.onboarding-step strong {
  font-size: 13px;
}

.onboarding-step small {
  margin-top: 4px;
  color: var(--fw-muted);
  line-height: 1.4;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

@media (max-width: 960px) {
  .opening-workbench {
    grid-template-columns: 1fr;
  }

  .onboarding-steps {
    grid-template-columns: 1fr;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
