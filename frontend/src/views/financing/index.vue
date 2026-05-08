<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <span style="font-size: 16px; font-weight: 600">融资服务</span>
      </template>

      <!-- 企业选择 + 评分展示 -->
      <div class="enterprise-selector">
        <el-form :inline="true">
          <el-form-item label="选择企业">
            <el-select v-model="selectedEnterpriseId" placeholder="请选择企业" style="width: 280px" filterable @change="onEnterpriseChange">
              <el-option v-for="e in enterprises" :key="e.id" :label="e.name" :value="e.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="currentScore !== null">
            <div class="current-score">
              当前评分：<span :class="'score-' + scoreClass">{{ currentScore }}</span>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <el-divider />

      <!-- 融资产品列表 -->
      <div class="products-grid">
        <el-card
          v-for="product in products"
          :key="product.id"
          class="product-card"
          :class="{ recommended: isRecommended(product) }"
          shadow="hover"
        >
          <template #header>
            <div class="product-header">
              <span class="product-name">{{ product.name }}</span>
              <el-tag v-if="isRecommended(product)" type="success" size="small">推荐</el-tag>
            </div>
          </template>
          <div class="product-body">
            <div class="product-row">
              <span class="label">年利率</span>
              <span class="value rate">{{ product.rate }}</span>
            </div>
            <div class="product-row">
              <span class="label">贷款额度</span>
              <span class="value amount">{{ product.amount }}</span>
            </div>
            <div class="product-row">
              <span class="label">贷款期限</span>
              <span class="value">{{ product.term }}</span>
            </div>
            <div class="product-row">
              <span class="label">评分要求</span>
              <span class="value" :class="'score-' + scoreClass(product.minScore)">{{ product.minScore }} 分起</span>
            </div>
            <div class="product-row">
              <span class="label">产品特点</span>
              <span class="value desc">{{ product.feature }}</span>
            </div>
          </div>
          <div class="product-footer">
            <el-button
              type="primary"
              :disabled="!isQualified(product)"
              @click="applyLoan(product)"
            >
              {{ isQualified(product) ? '申请贷款' : '评分不足' }}
            </el-button>
          </div>
        </el-card>
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

// Mock 融资产品数据
const products = ref([
  {
    id: 1,
    name: '税易贷',
    rate: '4.35% - 6.00%',
    amount: '最高 300 万',
    term: '12 个月',
    minScore: 650,
    feature: '凭纳税记录快速审批，纯信用'
  },
  {
    id: 2,
    name: '发票贷',
    rate: '5.22% - 8.00%',
    amount: '最高 500 万',
    term: '6-24 个月',
    minScore: 600,
    feature: '依据发票数据核定额度，循环使用'
  },
  {
    id: 3,
    name: '流水贷',
    rate: '6.00% - 10.00%',
    amount: '最高 100 万',
    term: '3-12 个月',
    minScore: 550,
    feature: '银行流水即可申请，审批快'
  },
  {
    id: 4,
    name: '担保贷',
    rate: '8.00% - 12.00%',
    amount: '最高 1000 万',
    term: '12-36 个月',
    minScore: 500,
    feature: '需要抵押或担保，额度更高'
  },
  {
    id: 5,
    name: '高新极速贷',
    rate: '3.85% - 5.50%',
    amount: '最高 500 万',
    term: '12 个月',
    minScore: 700,
    feature: '高新技术企业专属，利率优惠'
  },
  {
    id: 6,
    name: '供应链金融',
    rate: '5.00% - 7.50%',
    amount: '最高 800 万',
    term: '6-18 个月',
    minScore: 600,
    feature: '依托核心企业，批量授信'
  }
])

const scoreClass = (score) => {
  if (score == null) return ''
  if (score >= 700) return 'high'
  if (score >= 500) return 'mid'
  return 'low'
}

const isQualified = (product) => {
  return currentScore.value !== null && currentScore.value >= product.minScore
}

const isRecommended = (product) => {
  if (currentScore.value === null) return false
  return currentScore.value >= product.minScore && currentScore.value < product.minScore + 100
}

const onEnterpriseChange = async (id) => {
  if (!id) return
  // 从企业列表获取已有评分
  const ent = enterprises.value.find(e => e.id === id)
  if (ent && ent.financingScore != null) {
    currentScore.value = ent.financingScore
  } else {
    // 尝试调用融资评分接口
    try {
      const res = await api.post('/reports/financing/generate', { enterprise_id: id })
      currentScore.value = res.data.data?.financing_score || null
    } catch {
      currentScore.value = null
    }
  }
}

const applyLoan = (product) => {
  ElMessage.success(`已提交「${product.name}」贷款申请，客户经理将尽快与您联系`)
}

const fetchEnterprises = async () => {
  try {
    const res = await api.get('/enterprises', { params: { page: 1, page_size: 100 } })
    enterprises.value = res.data.items || []
  } catch {}
}

onMounted(fetchEnterprises)
</script>

<style scoped>
.page-container { width: 100%; }
.enterprise-selector { padding: 8px 0; }
.current-score { font-size: 14px; color: #666; }
.score-high { color: #67c23a; font-weight: bold; }
.score-mid { color: #e6a23c; font-weight: bold; }
.score-low { color: #f56c6c; font-weight: bold; }
.products-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 16px; }
.product-card.recommended { border: 2px solid #67c23a; }
.product-header { display: flex; justify-content: space-between; align-items: center; }
.product-name { font-weight: 700; font-size: 15px; color: #333; }
.product-body { padding: 4px 0; }
.product-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
.product-row:last-child { border-bottom: none; }
.label { color: #999; font-size: 13px; }
.value { font-weight: 600; font-size: 13px; color: #333; }
.value.rate { color: #f56c6c; }
.value.amount { color: #67c23a; }
.value.desc { font-weight: 400; color: #666; font-size: 12px; flex: 1; text-align: right; }
.product-footer { margin-top: 12px; text-align: center; }
</style>
