<template>
  <div class="dashboard">
    <!-- Stat Cards -->
    <el-row :gutter="20" class="stat-row">
      <el-col v-for="(stat, i) in stats" :key="stat.label" :span="6">
        <div class="stat-card" :style="{ '--accent': stat.color }">
          <div class="stat-icon-wrap">
            <span class="stat-icon" v-html="stat.icon"></span>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ stat.value }}</div>
            <div class="stat-label">{{ stat.label }}</div>
          </div>
          <div class="stat-trend" :class="stat.trendUp ? 'up' : 'down'">
            <span v-html="stat.trendUp ? arrowUp : arrowDown"></span>
            {{ stat.trend }}
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- Main Grid -->
    <el-row :gutter="20">
      <!-- Activity Feed -->
      <el-col :span="14">
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">最近操作</span>
            <span class="panel-meta">实时同步</span>
          </div>
          <div class="activity-list">
            <div v-for="item in activities" :key="item.id" class="activity-item">
              <div class="activity-dot" :style="{ background: item.color }"></div>
              <div class="activity-content">
                <div class="activity-text">{{ item.text }}</div>
                <div class="activity-meta">
                  <span class="activity-enterprise">{{ item.enterprise }}</span>
                  <span class="activity-time mono">{{ item.time }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-col>

      <!-- Quick Actions -->
      <el-col :span="10">
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">快捷操作</span>
          </div>
          <div class="quick-actions">
            <button
              v-for="action in quickActions"
              :key="action.label"
              class="quick-action-btn"
              @click="$router.push(action.path)"
            >
              <span class="qa-icon" v-html="action.icon"></span>
              <span class="qa-label">{{ action.label }}</span>
            </button>
          </div>
        </div>

        <!-- Financing Snapshot -->
        <div class="panel" style="margin-top: 20px;">
          <div class="panel-header">
            <span class="panel-title">融资概览</span>
            <span class="panel-link" @click="$router.push('/financing')">查看全部 →</span>
          </div>
          <div class="fin-snapshot">
            <div v-for="item in finSnapshot" :key="item.name" class="fin-row">
              <span class="fin-name">{{ item.name }}</span>
              <div class="fin-bar-wrap">
                <div class="fin-bar" :style="{ width: item.pct + '%', background: item.color }"></div>
              </div>
              <span class="fin-score" :style="{ color: item.color }">{{ item.score }}</span>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const arrowUp = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="18 15 12 9 6 15"/></svg>`
const arrowDown = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>`

const stats = ref([
  {
    label: '服务企业数',
    value: '12',
    color: '#cc785c',
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V7l8-4 8 4v14M9 21v-6h6v6"/></svg>`,
    trend: '+2 本月',
    trendUp: true
  },
  {
    label: '本月发票数',
    value: '256',
    color: '#3d6b4a',
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
    trend: '+18%',
    trendUp: true
  },
  {
    label: '待申报任务',
    value: '18',
    color: '#a86a1f',
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    trend: '需处理',
    trendUp: false
  },
  {
    label: '融资需求',
    value: '5',
    color: '#5a7a9a',
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><line x1="12" y1="6" x2="12" y2="8"/><line x1="12" y1="16" x2="12" y2="18"/></svg>`,
    trend: '待匹配',
    trendUp: false
  }
])

const activities = ref([
  { id: 1, text: '完成增值税申报', enterprise: '南京华瑞机械', time: '16:30', color: '#3d6b4a' },
  { id: 2, text: '导入银行对账单 23 条', enterprise: '苏州华锦纺织', time: '14:20', color: '#cc785c' },
  { id: 3, text: '生成财务健康报告', enterprise: '杭州鼎盛科技', time: '10:15', color: '#5a7a9a' },
  { id: 4, text: '发票匹配完成', enterprise: '南京华瑞机械', time: '09:45', color: '#3d6b4a' },
  { id: 5, text: '发起贷款申请', enterprise: '苏州华锦纺织', time: '昨天', color: '#a86a1f' }
])

const quickActions = [
  {
    label: '导入发票',
    path: '/invoices',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>`
  },
  {
    label: '发起申报',
    path: '/reports',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`
  },
  {
    label: '生成报告',
    path: '/reports',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`
  },
  {
    label: '添加企业',
    path: '/enterprises',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`
  }
]

const finSnapshot = ref([
  { name: '南京华瑞机械', score: 78, pct: 78, color: '#3d6b4a' },
  { name: '苏州华锦纺织', score: 65, pct: 65, color: '#a86a1f' },
  { name: '杭州鼎盛科技', score: 82, pct: 82, color: '#3d6b4a' },
  { name: '上海鼎丰贸易', score: 51, pct: 51, color: '#a86a1f' }
])
</script>

<style scoped>
.dashboard { width: 100%; }

/* === Stat Cards === */
.stat-row { margin-bottom: 20px; }

.stat-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition-base), transform var(--transition-base);
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: var(--accent);
}

.stat-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.stat-icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  flex-shrink: 0;
}

.stat-body { flex: 1; min-width: 0; }

.stat-value {
  font-size: 26px;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1.1;
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-trend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 20px;
}
.stat-trend.up { background: var(--color-success-light); color: var(--color-success); }
.stat-trend.down { background: var(--color-warning-light); color: var(--color-warning); }

/* === Panels === */
.panel {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-sm);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: 0.5px;
}

.panel-meta {
  font-size: 11px;
  color: var(--color-text-muted);
}

.panel-link {
  font-size: 12px;
  color: var(--color-accent);
  cursor: pointer;
  font-weight: 500;
}
.panel-link:hover { text-decoration: underline; }

/* === Activity === */
.activity-list { display: flex; flex-direction: column; gap: 0; }

.activity-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border-light);
}
.activity-item:last-child { border-bottom: none; }

.activity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}

.activity-text {
  font-size: 13px;
  color: var(--color-text-primary);
  font-weight: 500;
}

.activity-meta {
  display: flex;
  gap: 8px;
  margin-top: 2px;
}

.activity-enterprise {
  font-size: 12px;
  color: var(--color-text-muted);
}

.activity-time {
  font-size: 11px;
  color: var(--color-text-muted);
}

/* === Quick Actions === */
.quick-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.quick-action-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 12px;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.quick-action-btn:hover {
  background: var(--color-accent-bg);
  border-color: var(--color-accent);
}

.qa-icon { color: var(--color-accent); }
.qa-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); }

/* === Fin Snapshot === */
.fin-snapshot { display: flex; flex-direction: column; gap: 10px; }

.fin-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fin-name {
  width: 90px;
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.fin-bar-wrap {
  flex: 1;
  height: 6px;
  background: var(--color-bg-alt);
  border-radius: 3px;
  overflow: hidden;
}

.fin-bar {
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s ease;
}

.fin-score {
  font-size: 12px;
  font-weight: 700;
  width: 28px;
  text-align: right;
  flex-shrink: 0;
}
</style>