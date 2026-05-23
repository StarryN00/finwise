<template>
  <section class="enterprise-detail">
    <div class="detail-header">
      <div>
        <p class="caption">企业详情</p>
        <h2 class="section-title">{{ enterprise?.name || '未找到企业' }}</h2>
      </div>
      <el-button @click="router.push('/enterprises')">返回名册</el-button>
    </div>

    <template v-if="enterprise">
      <section class="detail-grid">
        <div class="detail-panel">
          <h3>基础信息</h3>
          <dl>
            <dt>企业名称</dt>
            <dd>{{ enterprise.name }}</dd>
            <dt>营业执照编号</dt>
            <dd>{{ enterprise.unifiedSocialCreditCode || '-' }}</dd>
            <dt>纳税人类型</dt>
            <dd>{{ enterprise.taxpayerType }}</dd>
            <dt>行业</dt>
            <dd>{{ enterprise.industry || '-' }}</dd>
          </dl>
        </div>

        <div class="detail-panel">
          <h3>补充信息</h3>
          <dl>
            <dt>省市</dt>
            <dd>{{ enterprise.province || '-' }} {{ enterprise.city || '' }}</dd>
            <dt>状态</dt>
            <dd>{{ enterprise.status === 'ACTIVE' ? '正常服务' : enterprise.status }}</dd>
            <dt>当前机构</dt>
            <dd>{{ workspace.activeOrganization }}</dd>
            <dt>客户标签</dt>
            <dd>苏州代账客户</dd>
          </dl>
        </div>

        <div class="detail-panel">
          <h3>期初数据导入</h3>
          <dl>
            <dt>导入状态</dt>
            <dd>{{ enterprise.latestMonth === '-' ? '待初始化' : '已建立月度数据' }}</dd>
            <dt>最近月份</dt>
            <dd>{{ enterprise.latestMonth }}</dd>
            <dt>资料状态</dt>
            <dd><StatusTag :status="enterprise.dataStatus" /></dd>
            <dt>报告状态</dt>
            <dd><StatusTag :status="enterprise.reportStatus" /></dd>
          </dl>
        </div>
      </section>

      <DataTableShell title="最近工作包" description="该企业最近的月度记账与申报进度">
        <el-table :data="enterprisePackages" stripe empty-text="暂无月度工作包">
          <el-table-column prop="period" label="期间" width="120" />
          <el-table-column label="状态" width="150">
            <template #default="{ row }"><StatusTag :status="row.status" /></template>
          </el-table-column>
          <el-table-column prop="pending" label="待确认" width="110" align="right" />
          <el-table-column prop="tax" label="税额估算" width="140" align="right" />
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" @click="goAccountDetails(row)">查看账目</el-button>
            </template>
          </el-table-column>
        </el-table>
      </DataTableShell>
    </template>

    <el-empty v-else description="企业不存在或尚未加载" />
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DataTableShell from '../components/DataTableShell.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const enterpriseId = computed(() => route.params.enterpriseId)

const enterprise = computed(() => workspace.enterprises.find((item) => item.id === enterpriseId.value))
const enterprisePackages = computed(() => workspace.workPackages.filter((item) => item.enterpriseId === enterpriseId.value))

async function goAccountDetails(packageRow) {
  await workspace.selectPackage(packageRow.id)
  router.push('/account-details')
}
</script>

<style scoped>
.enterprise-detail {
  display: grid;
  gap: 18px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.detail-header .caption {
  margin: 0 0 4px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.detail-panel {
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.detail-panel h3 {
  margin: 0 0 14px;
  font-size: 16px;
}

.detail-panel dl {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 10px 12px;
  margin: 0;
}

.detail-panel dt {
  color: var(--fw-ink-muted);
}

.detail-panel dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 700;
}

@media (max-width: 1100px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
