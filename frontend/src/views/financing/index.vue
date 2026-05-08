<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">融资服务</h1>
        <p class="page-desc">根据企业融资评分匹配最优银行产品</p>
      </div>
    </div>

    <el-card class="financing-card">
      <!-- Enterprise selector -->
      <div class="enterprise-selector">
        <el-select v-model="selectedEnterpriseId" placeholder="请选择企业" style="width:280px" filterable @change="onEnterpriseChange">
          <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
        </el-select>
        <div v-if="currentScore !== null" class="score-display">
          <span class="score-label">当前评分</span>
          <span class="score-value" :style="{ color: scoreColor }">{{ currentScore }}</span>
          <span class="score-suffix">分</span>
        </div>
      </div>

      <el-divider />

      <!-- Products grid -->
      <div class="products-grid">
        <div
          v-for="product in products"
          :key="product.id"
          class="product-card"
          :class="{ recommended: isRecommended(product), disabled: !isQualified(product) }"
        >
          <div class="product-card-inner">
            <div class="product-header">
              <span class="product-name">{{ product.name }}</span>
              <el-tag v-if="isRecommended(product)" type="success" size="small" class="rec-tag">推荐</el-tag>
            </div>
            <div class="product-body">
              <div class="product-row">
                <span class="pro-label">年利率</span>
                <span class="pro-value rate">{{ product.rate }}</span>
              </div>
              <div class="product-row">
                <span class="pro-label">贷款额度</span>
                <span class="pro-value amount">{{ product.amount }}</span>
              </div>
              <div class="product-row">
                <span class="pro-label">贷款期限</span>
                <span class="pro-value">{{ product.term }}</span>
              </div>
              <div class="product-row">
                <span class="pro-label">评分要求</span>
                <span class="pro-value" :class="currentScore !== null && currentScore < product.minScore ? 'text-warning' : 'text-success'">
                  {{ product.minScore }} 分起
                </span>
              </div>
              <div class="product-row">
                <span class="pro-label">产品特点</span>
                <span class="pro-value desc">{{ product.feature }}</span>
              </div>
            </div>
            <div class="product-footer">
              <el-button
                type="primary"
                :disabled="!isQualified(product)"
                class="apply-btn"
                @click="applyLoan(product)"
              >
                {{ isQualified(product) ? '申请贷款' : `评分不足(${currentScore}分)` }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <el-empty v-if="products.length === 0" description="暂无可用融资产品" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const selectedEnterpriseId = ref('')
const currentScore = ref(null)
const enterprises = ref([])

const scoreColor = computed(() => {
  if (currentScore.value === null) return '#9c9786'
  if (currentScore.value >= 70) return '#3d6b4a'
  if (currentScore.value >= 50) return '#a86a1f'
  return '#c0392b'
})

const products = ref([
  { id: 1, name: '税易贷', rate: '4.35% - 6.00%', amount: '最高 300 万', term: '12 个月', minScore: 65, feature: '凭纳税记录快速审批，纯信用' },
  { id: 2, name: '发票贷', rate: '5.22% - 8.00%', amount: '最高 500 万', term: '6-24 个月', minScore: 60, feature: '依据发票数据核定额度，循环使用' },
  { id: 3, name: '流水贷', rate: '6.00% - 10.00%', amount: '最高 100 万', term: '3-12 个月', minScore: 55, feature: '银行流水即可申请，审批快' },
  { id: 4, name: '担保贷', rate: '8.00% - 12.00%', amount: '最高 1000 万', term: '12-36 个月', minScore: 50, feature: '需要抵押或担保，额度更高' },
  { id: 5, name: '高新极速贷', rate: '3.85% - 5.50%', amount: '最高 500 万', term: '12 个月', minScore: 70, feature: '高新技术企业专属，利率优惠' },
  { id: 6, name: '供应链金融', rate: '5.00% - 7.50%', amount: '最高 800 万', term: '6-18 个月', minScore: 60, feature: '依托核心企业，批量授信' }
])

const isQualified = (product) => currentScore.value !== null && currentScore.value >= product.minScore
const isRecommended = (product) => currentScore.value !== null && currentScore.value >= product.minScore && currentScore.value < product.minScore + 20

const onEnterpriseChange = async (id) => {
  if (!id) return
  const ent = enterprises.value.find(e => e.id === id)
  if (ent?.financing_score != null) { currentScore.value = ent.financing_score; return }
  try {
    const res = await api.post('/api/reports/financing/generate', { enterprise_id: id })
    currentScore.value = res.data.data?.score || null
  } catch { currentScore.value = null }
}

const applyLoan = (product) => ElMessage.success(`已提交「${product.name}」贷款申请，客户经理将尽快与您联系`)

const fetchEnterprises = async () => {
  try {
    const res = await api.get('/api/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
  } catch {}
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page { width: 100%; }

.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-title { font-size: 20px; font-weight: 800; color: var(--color-text-primary); margin-bottom: 4px; }
.page-desc { font-size: 13px; color: var(--color-text-muted); }

.financing-card { border-radius: var(--radius-lg) !important; }

.enterprise-selector { display: flex; align-items: center; gap: 20px; }

.score-display { display: flex; align-items: baseline; gap: 4px; }
.score-label { font-size: 13px; color: var(--color-text-muted); }
.score-value { font-size: 28px; font-weight: 800; }
.score-suffix { font-size: 13px; color: var(--color-text-muted); }

.products-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 8px; }

.product-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  transition: all var(--transition-base);
  overflow: hidden;
}
.product-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.product-card.recommended { border-color: var(--color-success); }
.product-card.disabled { opacity: 0.6; }

.product-card-inner { padding: 18px; }

.product-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.product-name { font-weight: 700; font-size: 15px; color: var(--color-text-primary); }
.rec-tag { font-weight: 600; }

.product-body { display: flex; flex-direction: column; gap: 0; }
.product-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--color-border-light); }
.product-row:last-child { border-bottom: none; }
.pro-label { font-size: 12px; color: var(--color-text-muted); }
.pro-value { font-size: 13px; font-weight: 600; color: var(--color-text-primary); }
.pro-value.rate { color: var(--color-accent); }
.pro-value.amount { color: var(--color-success); }
.pro-value.desc { font-weight: 400; color: var(--color-text-secondary); font-size: 12px; text-align: right; flex: 1; margin-left: 8px; }

.product-footer { margin-top: 14px; }
.apply-btn { width: 100%; border-radius: var(--radius-md) !important; }
</style>