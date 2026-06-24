<template>
  <section class="init-page">
    <div class="init-header">
      <div>
        <p class="caption">企业初始化</p>
        <h2 class="section-title">新增企业并建立期初财务基线</h2>
      </div>
      <el-button type="primary" :loading="isSubmitting" @click="submitEnterprise">保存企业并建立期初数据</el-button>
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="init-form">
      <section class="panel">
        <h3>基础信息</h3>
        <div class="form-grid">
          <el-form-item label="企业名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入企业全称" clearable />
          </el-form-item>
          <el-form-item label="营业执照编号 / 统一社会信用代码" prop="unifiedSocialCreditCode">
            <el-input v-model="form.unifiedSocialCreditCode" placeholder="请输入营业执照编号" clearable />
          </el-form-item>
          <el-form-item label="纳税人类型" prop="taxpayerType">
            <el-select v-model="form.taxpayerType" placeholder="请选择纳税人类型">
              <el-option label="一般纳税人" value="GENERAL" />
              <el-option label="小规模纳税人" value="SMALL_SCALE" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属行业" prop="industry">
            <el-select v-model="form.industry" placeholder="请选择所属行业" filterable>
              <el-option v-for="industry in industryOptions" :key="industry" :label="industry" :value="industry" />
            </el-select>
          </el-form-item>
        </div>
      </section>

      <section class="panel">
        <h3>补充信息</h3>
        <div class="form-grid compact">
          <el-form-item label="省份">
            <el-select v-model="form.province" placeholder="请选择省份" filterable @change="syncCityForProvince">
              <el-option v-for="province in provinceOptions" :key="province" :label="province" :value="province" />
            </el-select>
          </el-form-item>
          <el-form-item label="城市">
            <el-select v-model="form.city" placeholder="请选择城市" filterable>
              <el-option v-for="city in cityOptions" :key="city" :label="city" :value="city" />
            </el-select>
          </el-form-item>
          <el-form-item label="联系人">
            <el-input v-model="form.contactName" placeholder="可选，仅用于内部备注" clearable />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.note" placeholder="可选" clearable />
          </el-form-item>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <h3>期初数据导入</h3>
            <p class="caption">资产负债表和利润表属于同一初始化步骤，用于建立企业期初财务基线。</p>
          </div>
          <el-tag :type="balanceStatus.type" effect="light">{{ balanceStatus.text }}</el-tag>
        </div>

        <div class="upload-pair">
          <el-upload drag action="#" :auto-upload="false" :limit="1" :on-change="parseBalanceSheet">
            <strong>资产负债表 Excel</strong>
            <span>{{ files.balanceSheet || '选择或拖入文件' }}</span>
            <em>{{ parseStatus.balanceSheet }}</em>
          </el-upload>
          <el-upload drag action="#" :auto-upload="false" :limit="1" :on-change="parseIncomeStatement">
            <strong>利润表 Excel</strong>
            <span>{{ files.incomeStatement || '选择或拖入文件' }}</span>
            <em>{{ parseStatus.incomeStatement }}</em>
          </el-upload>
        </div>

        <div class="statement-grid">
          <div>
            <h4>资产负债表关键科目</h4>
            <div class="form-grid compact">
              <el-form-item label="资产总计" prop="assetsTotal">
                <el-input v-model="form.assetsTotal" placeholder="0.00" />
              </el-form-item>
              <el-form-item label="负债合计" prop="liabilitiesTotal">
                <el-input v-model="form.liabilitiesTotal" placeholder="0.00" />
              </el-form-item>
              <el-form-item label="所有者权益合计" prop="equityTotal">
                <el-input v-model="form.equityTotal" placeholder="0.00" />
              </el-form-item>
              <el-form-item label="货币资金">
                <el-input v-model="form.cash" placeholder="0.00" />
              </el-form-item>
            </div>
          </div>

          <div>
            <h4>利润表关键科目</h4>
            <div class="form-grid compact">
              <el-form-item label="营业收入" prop="revenue">
                <el-input v-model="form.revenue" placeholder="0.00" />
              </el-form-item>
              <el-form-item label="营业成本">
                <el-input v-model="form.cost" placeholder="0.00" />
              </el-form-item>
              <el-form-item label="管理费用">
                <el-input v-model="form.adminExpense" placeholder="0.00" />
              </el-form-item>
              <el-form-item label="净利润" prop="netProfit">
                <el-input v-model="form.netProfit" placeholder="0.00" />
              </el-form-item>
            </div>
          </div>
        </div>
      </section>
    </el-form>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const router = useRouter()
const workspace = useWorkspaceStore()
const formRef = ref(null)
const isSubmitting = ref(false)
const files = reactive({
  balanceSheet: '',
  incomeStatement: '',
})
const parseStatus = reactive({
  balanceSheet: '上传后自动识别关键科目',
  incomeStatement: '上传后自动识别关键科目',
})

const industryOptions = [
  '制造业',
  '批发和零售业',
  '软件和信息技术服务业',
  '科学研究和技术服务业',
  '租赁和商务服务业',
  '建筑业',
  '交通运输、仓储和邮政业',
  '居民服务、修理和其他服务业',
]

const provinceCityMap = {
  江苏省: ['苏州市', '昆山市', '南京市', '无锡市', '常州市', '南通市'],
  上海市: ['上海市'],
  浙江省: ['杭州市', '宁波市', '嘉兴市', '湖州市', '绍兴市'],
  安徽省: ['合肥市', '芜湖市', '马鞍山市', '滁州市'],
}

const provinceOptions = Object.keys(provinceCityMap)

const form = reactive({
  name: '',
  unifiedSocialCreditCode: '',
  taxpayerType: 'GENERAL',
  industry: '',
  province: '江苏省',
  city: '苏州市',
  contactName: '',
  note: '',
  assetsTotal: '',
  liabilitiesTotal: '',
  equityTotal: '',
  cash: '',
  revenue: '',
  cost: '',
  adminExpense: '',
  netProfit: '',
})

const requiredText = (message) => (_rule, value, callback) => {
  if (!String(value || '').trim()) {
    callback(new Error(message))
    return
  }
  callback()
}

const rules = {
  name: [{ required: true, validator: requiredText('请输入企业名称'), trigger: 'blur' }],
  unifiedSocialCreditCode: [{ required: true, validator: requiredText('请输入营业执照编号'), trigger: 'blur' }],
  taxpayerType: [{ required: true, message: '请选择纳税人类型', trigger: 'change' }],
  industry: [{ required: true, validator: requiredText('请输入所属行业'), trigger: 'blur' }],
  assetsTotal: [{ required: true, validator: requiredText('请输入资产总计'), trigger: 'blur' }],
  liabilitiesTotal: [{ required: true, validator: requiredText('请输入负债合计'), trigger: 'blur' }],
  equityTotal: [{ required: true, validator: requiredText('请输入所有者权益合计'), trigger: 'blur' }],
  revenue: [{ required: true, validator: requiredText('请输入营业收入'), trigger: 'blur' }],
  netProfit: [{ required: true, validator: requiredText('请输入净利润'), trigger: 'blur' }],
}

const balanceStatus = computed(() => {
  const assets = toNumber(form.assetsTotal)
  const liabilities = toNumber(form.liabilitiesTotal)
  const equity = toNumber(form.equityTotal)
  if ([form.assetsTotal, form.liabilitiesTotal, form.equityTotal].some((value) => !String(value).trim())) {
    return { text: '待录入', type: 'warning' }
  }
  return Math.abs(assets - liabilities - equity) < 0.01
    ? { text: '资产负债平衡', type: 'success' }
    : { text: '需复核平衡关系', type: 'danger' }
})

const cityOptions = computed(() => provinceCityMap[form.province] || [])

async function parseBalanceSheet(file) {
  files.balanceSheet = file.name
  parseStatus.balanceSheet = '正在解析...'
  try {
    const data = await parseStatementFile(file, 'BALANCE_SHEET')
    form.assetsTotal = data.data['资产总计'] || form.assetsTotal
    form.liabilitiesTotal = data.data['负债合计'] || form.liabilitiesTotal
    form.equityTotal = data.data['所有者权益合计'] || form.equityTotal
    form.cash = data.data['货币资金'] || form.cash
    parseStatus.balanceSheet = statusText(data)
    ElMessage.success('资产负债表关键科目已回填')
  } catch (error) {
    parseStatus.balanceSheet = '解析失败，请手动填写'
    ElMessage.error(error?.response?.data?.detail || error?.message || '资产负债表解析失败')
  }
}

async function parseIncomeStatement(file) {
  files.incomeStatement = file.name
  parseStatus.incomeStatement = '正在解析...'
  try {
    const data = await parseStatementFile(file, 'INCOME_STATEMENT')
    form.revenue = data.data['营业收入'] || form.revenue
    form.cost = data.data['营业成本'] || form.cost
    form.adminExpense = data.data['管理费用'] || form.adminExpense
    form.netProfit = data.data['净利润'] || form.netProfit
    parseStatus.incomeStatement = statusText(data)
    ElMessage.success('利润表关键科目已回填')
  } catch (error) {
    parseStatus.incomeStatement = '解析失败，请手动填写'
    ElMessage.error(error?.response?.data?.detail || error?.message || '利润表解析失败')
  }
}

function syncCityForProvince() {
  const availableCities = cityOptions.value
  if (!availableCities.includes(form.city)) {
    form.city = availableCities[0] || ''
  }
}

async function parseStatementFile(file, statementType) {
  const formData = new FormData()
  formData.append('statement_type', statementType)
  formData.append('file', file.raw)
  const response = await api.initialStatements.parse(formData)
  return response.data
}

function statusText(result) {
  if (!result.missing_fields.length) {
    return '已识别全部必需科目'
  }
  return `缺失：${result.missing_fields.join('、')}`
}

async function submitEnterprise() {
  try {
    await formRef.value?.validate()
  } catch {
    ElMessage.warning('请先补齐必填信息')
    return
  }
  isSubmitting.value = true
  try {
    const enterpriseResponse = await api.enterprises.create({
      name: form.name.trim(),
      unified_social_credit_code: form.unifiedSocialCreditCode.trim(),
      taxpayer_type: form.taxpayerType,
      industry: form.industry.trim(),
      province: form.province.trim() || '江苏省',
      city: form.city.trim() || '苏州市',
    })
    await api.enterprises.initialize(enterpriseResponse.data.id, {
      balance_sheet_data: {
        资产总计: form.assetsTotal,
        负债合计: form.liabilitiesTotal,
        所有者权益合计: form.equityTotal,
        货币资金: form.cash,
      },
      income_statement_data: {
        营业收入: form.revenue,
        营业成本: form.cost,
        管理费用: form.adminExpense,
        净利润: form.netProfit,
      },
    })
    await workspace.loadWorkspace()
    ElMessage.success('企业和期初数据已保存')
    router.push('/enterprises')
  } catch (error) {
    ElMessage.error(formatEnterpriseSaveError(error))
  } finally {
    isSubmitting.value = false
  }
}

function formatEnterpriseSaveError(error) {
  const detail = error?.response?.data?.detail || error?.message || ''
  if (
    error?.response?.status === 409 ||
    detail.includes('unified social credit code already exists') ||
    detail.includes('统一社会信用代码已存在')
  ) {
    return '该统一社会信用代码已存在，请检查是否已保存过该企业。企业档案可能已经创建成功，请返回企业名册确认后再继续。'
  }
  if (detail.includes('Initial financial snapshot') || detail.includes('期初数据已保存')) {
    return '该企业的期初数据已保存，请勿重复提交。'
  }
  if (detail.includes('required') || detail.includes('请填写') || detail.includes('请选择')) {
    return detail
  }
  return detail || '保存失败，请稍后重试'
}

function toNumber(value) {
  const parsed = Number(String(value || '').replace(/,/g, ''))
  return Number.isFinite(parsed) ? parsed : 0
}
</script>

<style scoped>
.init-page {
  display: grid;
  gap: 16px;
}

.init-header,
.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.init-header .caption,
.panel-heading .caption {
  margin: 0 0 4px;
}

.init-form {
  display: grid;
  gap: 16px;
}

.panel {
  padding: 18px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.panel h3,
.panel h4 {
  margin: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
  margin-top: 16px;
}

.form-grid.compact {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.upload-pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.upload-pair strong,
.upload-pair span,
.upload-pair em {
  display: block;
}

.upload-pair span,
.upload-pair em {
  margin-top: 6px;
  color: var(--fw-text-muted);
  font-size: 13px;
}

.upload-pair em {
  font-style: normal;
}

.statement-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--fw-line);
}

@media (max-width: 1100px) {
  .form-grid.compact {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .statement-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .init-header,
  .panel-heading,
  .upload-pair,
  .form-grid,
  .form-grid.compact {
    grid-template-columns: 1fr;
  }

  .init-header,
  .panel-heading {
    display: grid;
  }
}
</style>
