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

      <section class="technology-profile-panel">
        <div class="panel-heading">
          <div>
            <h3>科技资质画像</h3>
            <p class="caption">按照企查查科创分结构展示科技型企业认定和知识产权数量。</p>
          </div>
          <div class="panel-actions">
            <el-button type="primary" plain @click="qichachaTextDialog = true">导入企查查科创分文本</el-button>
            <el-tag :type="formatTechnologyStatus(technologyProfile?.overall_status).type" effect="light">
              {{ formatTechnologyStatus(technologyProfile?.overall_status).label }}
            </el-tag>
          </div>
        </div>

        <div class="technology-summary">
          <div>
            <span>数据来源</span>
            <strong>{{ technologyProfile?.primary_provider || '待扫描' }}</strong>
          </div>
          <div>
            <span>最近扫描</span>
            <strong>{{ formatDateTime(technologyProfile?.last_scanned_at) }}</strong>
          </div>
          <div>
            <span>摘要</span>
            <strong>{{ technologyProfile?.summary || '暂无科技画像数据' }}</strong>
          </div>
        </div>

        <div class="technology-groups">
          <div class="technology-group">
            <h4>科技型企业认定</h4>
            <div class="tag-list">
              <el-tag v-for="tag in tagsByCategory.QCC_TECH_CERTIFICATION" :key="tag.id" effect="light">
                {{ tag.name }}{{ tag.value ? ` · ${tag.value}` : '' }}
              </el-tag>
              <span v-if="!tagsByCategory.QCC_TECH_CERTIFICATION.length" class="empty-hint">暂无点亮项目</span>
            </div>
          </div>
          <div class="technology-group">
            <h4>知识产权</h4>
            <div class="tag-list">
              <el-tag v-for="tag in tagsByCategory.QCC_INTELLECTUAL_PROPERTY" :key="tag.id" type="success" effect="light">
                {{ tag.name }}{{ tag.value ? ` · ${tag.value}` : '' }}
              </el-tag>
              <span v-if="!tagsByCategory.QCC_INTELLECTUAL_PROPERTY.length" class="empty-hint">暂无数量</span>
            </div>
          </div>
        </div>

        <el-table :data="technologyProfile?.tags || []" stripe empty-text="暂无科技画像标签">
          <el-table-column prop="name" label="标签" min-width="160" />
          <el-table-column label="类别" width="130">
            <template #default="{ row }">{{ formatTechnologyCategory(row.category) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="formatTagStatus(row.status).type" effect="light">
                {{ formatTagStatus(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="confidence" label="可信度" width="90" align="right" />
          <el-table-column prop="source_provider" label="来源" width="110" />
          <el-table-column prop="evidence_text" label="证据" min-width="240" show-overflow-tooltip />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="row.status !== 'PENDING_REVIEW'" @click="confirmTechnologyTag(row)">确认</el-button>
              <el-button link type="danger" :disabled="row.status !== 'PENDING_REVIEW'" @click="rejectTechnologyTag(row)">驳回</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-dialog v-model="qichachaTextDialog" title="导入企查查科创分文本" width="720px">
          <div class="qichacha-text-form">
            <p class="caption">在企查查科创分弹窗中复制“科技型企业认定情况”和“知识产权取得情况”的文本后粘贴到这里。</p>
            <el-input v-model="qichachaSourceUrl" placeholder="企查查来源链接（可选）" clearable />
            <el-input
              v-model="qichachaInnovationText"
              type="textarea"
              :rows="12"
              placeholder="粘贴企查查科创分弹窗文本"
            />
          </div>
          <template #footer>
            <el-button @click="qichachaTextDialog = false">取消</el-button>
            <el-button type="primary" :loading="isImportingQichachaText" @click="submitQichachaText">解析并导入</el-button>
          </template>
        </el-dialog>
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
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import DataTableShell from '../components/DataTableShell.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const enterpriseId = computed(() => route.params.enterpriseId)
const technologyProfile = ref(null)
const qichachaTextDialog = ref(false)
const qichachaInnovationText = ref('')
const qichachaSourceUrl = ref('')
const isImportingQichachaText = ref(false)

const enterprise = computed(() => workspace.enterprises.find((item) => item.id === enterpriseId.value))
const enterprisePackages = computed(() => workspace.workPackages.filter((item) => item.enterpriseId === enterpriseId.value))
const tagsByCategory = computed(() => {
  const groups = {
    QCC_TECH_CERTIFICATION: [],
    QCC_INTELLECTUAL_PROPERTY: [],
  }
  for (const tag of technologyProfile.value?.tags || []) {
    if (tag.status === 'NOT_HIT') continue
    if (groups[tag.category]) groups[tag.category].push(tag)
  }
  return groups
})

watch(
  enterpriseId,
  () => {
    loadTechnologyProfile()
  },
  { immediate: true }
)

async function goAccountDetails(packageRow) {
  await workspace.selectPackage(packageRow.id)
  router.push('/account-details')
}

async function loadTechnologyProfile() {
  if (!enterpriseId.value) return
  const response = await api.technologyProfile.get(enterpriseId.value)
  technologyProfile.value = response.data
}

async function confirmTechnologyTag(row) {
  await api.technologyProfile.confirmTag(row.id)
  await loadTechnologyProfile()
  await workspace.loadWorkspace()
  ElMessage.success('科技画像标签已确认')
}

async function rejectTechnologyTag(row) {
  await api.technologyProfile.rejectTag(row.id)
  await loadTechnologyProfile()
  await workspace.loadWorkspace()
  ElMessage.success('科技画像标签已驳回')
}

async function submitQichachaText() {
  const text = qichachaInnovationText.value.trim()
  if (!text) {
    ElMessage.warning('请先粘贴企查查科创分文本')
    return
  }
  isImportingQichachaText.value = true
  try {
    await api.technologyProfile.upsert(enterpriseId.value, {
      provider: 'QICHACHA',
      source_url: qichachaSourceUrl.value.trim() || undefined,
      qichacha_innovation_text: text,
    })
    qichachaTextDialog.value = false
    qichachaInnovationText.value = ''
    qichachaSourceUrl.value = ''
    await loadTechnologyProfile()
    await workspace.loadWorkspace()
    ElMessage.success('企查查科创分文本已解析入库')
  } finally {
    isImportingQichachaText.value = false
  }
}

function formatTechnologyStatus(status) {
  const statusMap = {
    NOT_SCANNED: { label: '未扫描', type: 'info' },
    SCANNED_PENDING_REVIEW: { label: '待确认', type: 'warning' },
    CONFIRMED: { label: '已确认', type: 'success' },
    NEEDS_RESCAN: { label: '需复查', type: 'danger' },
    FAILED: { label: '扫描失败', type: 'danger' },
  }
  return statusMap[status] || { label: status || '未扫描', type: 'info' }
}

function formatTechnologyCategory(category) {
  const categoryMap = {
    TECH_QUALIFICATION: '科技认证',
    INTELLECTUAL_PROPERTY: '知识产权',
    QCC_TECH_CERTIFICATION: '科技型企业认定',
    QCC_INTELLECTUAL_PROPERTY: '知识产权',
    CERTIFICATION: '体系认证',
    SERVICE_OPPORTUNITY: '服务机会',
    RISK_SIGNAL: '风险信号',
  }
  return categoryMap[category] || category
}

function formatTagStatus(status) {
  const statusMap = {
    HIT: { label: '已命中', type: 'success' },
    NOT_HIT: { label: '未命中', type: 'info' },
    PENDING_REVIEW: { label: '待确认', type: 'warning' },
    UNKNOWN: { label: '无法判断', type: 'info' },
  }
  return statusMap[status] || { label: status || '无法判断', type: 'info' }
}

function formatDateTime(value) {
  if (!value) return '未扫描'
  return String(value).slice(0, 16).replace('T', ' ')
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

.technology-profile-panel {
  display: grid;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.panel-heading h3,
.technology-group h4 {
  margin: 0;
}

.technology-summary {
  display: grid;
  grid-template-columns: 180px 180px minmax(0, 1fr);
  gap: 12px;
}

.technology-summary div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.technology-summary span,
.empty-hint {
  color: var(--fw-ink-muted);
  font-size: 12px;
}

.technology-summary strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.technology-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.technology-group {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-bg);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.qichacha-text-form {
  display: grid;
  gap: 12px;
}

.qichacha-text-form .caption {
  margin: 0;
}

@media (max-width: 1100px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .technology-summary,
  .technology-groups {
    grid-template-columns: 1fr;
  }
}
</style>
