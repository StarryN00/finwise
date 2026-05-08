<template>
  <div class="finwise-layout">
    <!-- 侧边栏 -->
    <aside class="finwise-sidebar">
      <div class="sidebar-brand">
        <div class="brand-icon">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <rect width="28" height="28" rx="8" fill="#cc785c"/>
            <path d="M7 20V12l7-4 7 4v8l-7 4-7-4z" fill="white" opacity="0.9"/>
            <path d="M14 8v12M7 12l7 4 7-4" stroke="white" stroke-width="1.5" fill="none"/>
          </svg>
        </div>
        <span class="brand-name">智税管家</span>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <span class="nav-icon" v-html="item.icon"></span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="footer-user">
          <div class="user-avatar">操</div>
          <div class="user-info">
            <div class="user-name">操作员</div>
            <div class="user-role">业务运营</div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="finwise-main">
      <!-- 顶部 Header -->
      <header class="finwise-header">
        <div class="header-breadcrumb">
          <span class="page-title">{{ currentPageTitle }}</span>
        </div>
        <div class="header-actions">
          <button class="header-btn" title="消息通知">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
          </button>
          <button class="header-btn" title="退出登录" @click="handleLogout">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="finwise-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const navItems = [
  {
    path: '/',
    label: '工作台',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`
  },
  {
    path: '/enterprises',
    label: '企业管理',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V7l8-4 8 4v14M9 21v-6h6v6"/></svg>`
  },
  {
    path: '/invoices',
    label: '发票管理',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`
  },
  {
    path: '/reports',
    label: '财务报表',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`
  },
  {
    path: '/financing',
    label: '融资服务',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><line x1="12" y1="6" x2="12" y2="8"/><line x1="12" y1="16" x2="12" y2="18"/></svg>`
  }
]

const isActive = (path) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

const currentPageTitle = computed(() => {
  const item = navItems.find(n => isActive(n.path))
  return item ? item.label : '智税管家'
})

const handleLogout = () => {
  localStorage.removeItem('token')
  router.push('/login')
}
</script>

<style scoped>
/* === Layout Shell === */
.finwise-layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg);
}

/* === Sidebar === */
.finwise-sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-bg-card);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 100;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 20px 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: 2px;
}

/* === Navigation === */
.sidebar-nav {
  flex: 1;
  padding: 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.nav-item:hover {
  background: var(--color-bg-alt);
  color: var(--color-accent);
}

.nav-item.active {
  background: var(--color-accent-bg);
  color: var(--color-accent);
}

.nav-item.active .nav-icon {
  color: var(--color-accent);
}

.nav-icon {
  display: flex;
  align-items: center;
  color: var(--color-text-muted);
  transition: color var(--transition-fast);
}

.nav-label {
  font-weight: 500;
}

/* === Sidebar Footer === */
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--color-border-light);
}

.footer-user {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--color-accent);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.user-info {
  min-width: 0;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 11px;
  color: var(--color-text-muted);
}

/* === Main Area === */
.finwise-main {
  flex: 1;
  margin-left: 220px;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* === Header === */
.finwise-header {
  height: 60px;
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 50;
}

.header-breadcrumb {
  display: flex;
  align-items: center;
}

.page-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: 1px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.header-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--color-text-muted);
  transition: all var(--transition-fast);
}

.header-btn:hover {
  background: var(--color-bg-alt);
  color: var(--color-accent);
}

/* === Content === */
.finwise-content {
  flex: 1;
  padding: 24px;
}
</style>