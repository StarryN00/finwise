<script setup>
import { Plus } from '@element-plus/icons-vue'

const navItems = ['工作台', '企业名册', '月度工作包', '账目明细', '申报辅助', '输出中心', '规则设置']
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div class="brand-lockup">
        <div class="brand-mark">智</div>
        <div>
          <strong>智税管家</strong>
          <span>代账月度工作台</span>
        </div>
      </div>
      <nav class="app-nav" aria-label="主导航">
        <a v-for="item in navItems" :key="item" href="#" class="app-nav__item" :class="{ active: item === '工作台' }">
          <span class="app-nav__dot" />
          <span>{{ item }}</span>
        </a>
      </nav>
    </aside>

    <div class="app-main">
      <header class="app-topbar">
        <div>
          <p class="caption">苏州代账公司 · Phase 1</p>
          <h1 class="page-title">月度记账与申报工作台</h1>
        </div>
        <el-button type="primary" :icon="Plus">创建本月工作包</el-button>
      </header>
      <main class="app-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 100vh;
}

.app-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 20px 14px;
  overflow-y: auto;
  color: #d9e7fb;
  background: #0f1d32;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--fw-radius-sm);
  color: var(--fw-brand-dark);
  background: #ffffff;
  font-weight: 800;
}

.brand-lockup strong {
  display: block;
  font-size: 16px;
  line-height: 1.2;
}

.brand-lockup span {
  display: block;
  margin-top: 2px;
  color: #9bb1ce;
  font-size: 12px;
}

.app-nav {
  display: grid;
  gap: 4px;
  margin-top: 18px;
}

.app-nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 8px 10px;
  border-radius: var(--fw-radius-sm);
  color: #b9cae2;
  font-size: 13px;
}

.app-nav__item:hover,
.app-nav__item.active {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

.app-nav__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #5b74a0;
}

.app-nav__item.active .app-nav__dot {
  background: var(--fw-brand);
}

.app-main {
  min-width: 0;
}

.app-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 82px;
  padding: 18px 28px;
  background: var(--fw-surface);
  border-bottom: 1px solid var(--fw-line);
}

.app-topbar .caption {
  margin: 0 0 4px;
}

.app-content {
  display: grid;
  gap: 18px;
  padding: 24px 28px 40px;
}

@media (max-width: 860px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .app-sidebar {
    position: static;
    height: auto;
  }

  .app-topbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
