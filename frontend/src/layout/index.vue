<template>
  <div class="finwise-layout">
    <!-- 侧边栏 -->
    <aside class="finwise-sidebar">
      <div class="sidebar-brand">
        <div class="brand-icon">
          <svg width="30" height="30" viewBox="0 0 30 30" fill="none">
            <rect width="30" height="30" rx="8" fill="var(--accent)"/>
            <path d="M8 22V13l7-4 7 4v9l-7 4-7-4z" fill="white" opacity="0.9"/>
            <path d="M15 9v13M8 13l7 4 7-4" stroke="white" stroke-width="1.5" fill="none"/>
          </svg>
        </div>
        <span class="brand-name">FinWise</span>
      </div>

      <nav class="sidebar-nav">
        <div class="nav-group">
          <div class="nav-group-title">§ 01 · WORKSPACE</div>
          <router-link
            v-for="item in workspaceNav"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: isActive(item.path) }"
          >
            <span class="nav-icon" v-html="item.icon"></span>
            <span class="nav-label">{{ item.label }}</span>
          </router-link>
        </div>

        <div class="nav-group">
          <div class="nav-group-title">§ 02 · ENTERPRISE</div>
          <router-link
            v-for="item in enterpriseNav"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: isActive(item.path) }"
          >
            <span class="nav-icon" v-html="item.icon"></span>
            <span class="nav-label">{{ item.label }}</span>
          </router-link>
        </div>
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
        <!-- Center nav -->
        <nav class="header-nav">
          <router-link
            v-for="item in headerNav"
            :key="item.path"
            :to="item.path"
            class="header-nav-item"
            :class="{ active: isActive(item.path) }"
          >
            {{ item.label }}
          </router-link>
        </nav>

        <!-- Right: status + time + avatar -->
        <div class="header-right">
          <div class="sys-status">
            <span class="status-dot"></span>
            <span class="status-time mono">{{ currentTime }}</span>
          </div>
          <div class="header-avatar">操</div>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()

const workspaceNav = [
  {
    path: '/',
    label: '工作台',
    icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`
  },
  {
    path: '/reports',
    label: '财务报表',
    icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`
  },
  {
    path: '/financing',
    label: '融资服务',
    icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 8v4l3 3"/></svg>`
  }
]

const enterpriseNav = [
  {
    path: '/enterprises',
    label: '企业管理',
    icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 21h18M5 21V7l8-4 8 4v14M9 21v-6h6v6"/></svg>`
  },
  {
    path: '/invoices',
    label: '发票管理',
    icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`
  }
]

const headerNav = computed(() => {
  const all = [...workspaceNav, ...enterpriseNav]
  return all
})

const isActive = (path) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

// Live clock
const currentTime = ref('')
let timer = null
const tick = () => {
  const now = new Date()
  const h = String(now.getHours()).padStart(2, '0')
  const m = String(now.getMinutes()).padStart(2, '0')
  const s = String(now.getSeconds()).padStart(2, '0')
  currentTime.value = `${h}:${m}:${s}`
}
onMounted(() => { tick(); timer = setInterval(tick, 1000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
/* === Layout Shell === */
.finwise-layout {
  display: flex;
  min-height: 100vh;
  background: var(--bg);
}

/* === Sidebar === */
.finwise-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--bg);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 100;
}

.sidebar-brand {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}

.brand-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.04em;
}

/* === Navigation === */
.sidebar-nav {
  flex: 1;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-group-title {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
  padding: 4px 12px 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  color: var(--ink-2);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 400;
  transition: all .15s ease;
  cursor: pointer;
  border-left: 2px solid transparent;
}

.nav-item:hover {
  background: var(--panel);
  color: var(--ink);
  border-left-color: var(--line);
}

.nav-item.active {
  background: var(--panel);
  color: var(--ink);
  border-left: 2px solid var(--accent);
  font-weight: 500;
}

.nav-icon {
  display: flex;
  align-items: center;
  color: var(--mute);
  flex-shrink: 0;
  transition: color .15s;
}
.nav-item.active .nav-icon,
.nav-item:hover .nav-icon { color: var(--ink); }

.nav-label { font-weight: 400; }
.nav-item.active .nav-label { font-weight: 500; }

/* === Sidebar Footer === */
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--line);
}

.footer-user {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--accent);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.user-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 11px;
  color: var(--mute);
}

/* === Main Area === */
.finwise-main {
  flex: 1;
  margin-left: 240px;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* === Header === */
.finwise-header {
  height: 64px;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  position: sticky;
  top: 0;
  z-index: 50;
}

.header-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 100%;
}

.header-nav-item {
  height: 64px;
  display: inline-flex;
  align-items: center;
  padding: 0 16px;
  font-size: 14px;
  color: var(--ink-2);
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: all .15s;
  white-space: nowrap;
}
.header-nav-item:hover { color: var(--ink); }
.header-nav-item.active {
  color: var(--ink);
  border-bottom-color: var(--accent);
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.sys-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ok-fg);
  flex-shrink: 0;
}

.status-time {
  font-size: 12px;
  color: var(--mute);
  letter-spacing: 0.05em;
}

.header-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--accent);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

/* === Content === */
.finwise-content {
  flex: 1;
  padding: 32px;
}
</style>
