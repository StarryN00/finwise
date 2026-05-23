<template>
  <section class="rules-layout">
    <div class="panel">
      <div class="panel-header">
        <div>
          <h2 class="section-title">规则设置</h2>
          <p class="caption">维护企业级摘要关键词、对方户名和业务类型规则</p>
        </div>
        <el-select v-model="selectedEnterpriseId" placeholder="选择企业" filterable style="width: 260px" @change="loadRules">
          <el-option
            v-for="enterprise in workspace.enterprises"
            :key="enterprise.id"
            :label="enterprise.name"
            :value="enterprise.id"
          />
        </el-select>
      </div>

      <el-table v-loading="isLoading" :data="rules" stripe>
        <el-table-column label="关键词" min-width="180">
          <template #default="{ row }">
            <el-tag v-for="keyword in row.summary_keywords" :key="keyword" size="small">{{ keyword }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="counterparty_pattern" label="对方户名" min-width="160" />
        <el-table-column label="业务类型" width="180">
          <template #default="{ row }">{{ businessTypeLabel(row.suggested_business_type) }}</template>
        </el-table-column>
        <el-table-column prop="invoice_direction" label="方向" width="110" />
        <el-table-column prop="source" label="来源" width="130" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeRule(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <h2 class="section-title">新增规则</h2>
      <el-form label-position="top" class="rule-form">
        <el-form-item label="摘要关键词">
          <el-input v-model="form.summaryKeywords" placeholder="多个关键词用逗号分隔" />
        </el-form-item>
        <el-form-item label="对方户名包含">
          <el-input v-model="form.counterpartyPattern" placeholder="可选" />
        </el-form-item>
        <el-form-item label="业务类型">
          <el-input v-model="form.businessType" placeholder="例如：银行手续费 / 咨询服务 / 销售收入" />
        </el-form-item>
        <el-form-item label="收支方向">
          <el-select v-model="form.invoiceDirection" clearable placeholder="可选">
            <el-option label="收入/销项" value="OUTPUT" />
            <el-option label="支出/进项" value="INPUT" />
          </el-select>
        </el-form-item>
        <el-button type="primary" :loading="isSaving" @click="createRule">保存规则</el-button>
      </el-form>
    </div>
  </section>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const selectedEnterpriseId = ref('')
const rules = ref([])
const isLoading = ref(false)
const isSaving = ref(false)
const form = reactive({
  summaryKeywords: '',
  counterpartyPattern: '',
  businessType: '',
  invoiceDirection: '',
})

watch(
  () => workspace.enterprises,
  (enterprises) => {
    if (!selectedEnterpriseId.value && enterprises.length) {
      selectedEnterpriseId.value = enterprises[0].id
      loadRules()
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (selectedEnterpriseId.value) loadRules()
})

async function loadRules() {
  if (!selectedEnterpriseId.value) return
  isLoading.value = true
  try {
    const response = await api.rules.list(selectedEnterpriseId.value)
    rules.value = response.data
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '规则加载失败')
  } finally {
    isLoading.value = false
  }
}

async function createRule() {
  const keywords = form.summaryKeywords
    .split(/[，,]/)
    .map((item) => item.trim())
    .filter(Boolean)
  if (!selectedEnterpriseId.value || !keywords.length || !form.businessType.trim()) {
    ElMessage.warning('请填写企业、关键词和业务类型')
    return
  }
  isSaving.value = true
  try {
    await api.rules.create({
      enterprise_id: selectedEnterpriseId.value,
      summary_keywords: keywords,
      counterparty_pattern: form.counterpartyPattern.trim() || null,
      suggested_business_type: form.businessType.trim(),
      invoice_direction: form.invoiceDirection || null,
    })
    form.summaryKeywords = ''
    form.counterpartyPattern = ''
    form.businessType = ''
    form.invoiceDirection = ''
    await loadRules()
    ElMessage.success('规则已保存')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '规则保存失败')
  } finally {
    isSaving.value = false
  }
}

async function removeRule(rule) {
  try {
    await ElMessageBox.confirm('删除后不会再用于后续自动匹配，确认删除？', '删除规则', { type: 'warning' })
    await api.rules.remove(rule.id)
    await loadRules()
    ElMessage.success('规则已删除')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error?.response?.data?.detail || error?.message || '规则删除失败')
    }
  }
}

function businessTypeLabel(value) {
  const labels = {
    AUTO_EXACT: '自动匹配',
    AI_SUGGESTED: 'AI 建议匹配',
    AI_FALLBACK_RULE: '需要规则匹配',
    AI_FALLBACK_CANDIDATE: '疑似匹配候选',
    MANUAL_CANDIDATE: '人工候选',
    MANUAL_INVOICE_ONLY: '手工确认发票',
    RULE: '规则匹配',
    BANK_FEE: '银行手续费',
    CONSULTING_SERVICE: '咨询服务',
    OTHER_EXPENSE: '其他支出',
    OTHER_INCOME: '其他收入',
    OUTPUT_REVENUE: '销售收入',
    INVOICE_CONFIRMED: '发票确认',
  }
  return labels[value] || value || '待确认'
}
</script>

<style scoped>
.rules-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px;
}

.panel {
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.panel-header .caption {
  margin: 4px 0 0;
}

.rule-form {
  margin-top: 14px;
}

.el-tag + .el-tag {
  margin-left: 6px;
}

@media (max-width: 980px) {
  .rules-layout {
    grid-template-columns: 1fr;
  }

  .panel-header {
    display: grid;
  }
}
</style>
