<script setup>
defineProps({
  label: {
    type: String,
    required: true,
  },
  value: {
    type: [String, Number],
    required: true,
  },
  subtext: {
    type: String,
    default: '',
  },
  tone: {
    type: String,
    default: 'default',
  },
})
</script>

<template>
  <section class="metric-card" :class="`metric-card--${tone}`">
    <div class="metric-card__label">{{ label }}</div>
    <div class="metric-card__value">{{ value }}</div>
    <div v-if="subtext" class="metric-card__subtext">{{ subtext }}</div>
  </section>
</template>

<style scoped>
.metric-card {
  min-height: 108px;
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.metric-card__label {
  color: var(--fw-ink-soft);
  font-size: 13px;
  font-weight: 700;
}

.metric-card__value {
  margin-top: 8px;
  color: var(--fw-ink);
  font-size: 24px;
  font-weight: 800;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.metric-card__subtext {
  margin-top: 8px;
  color: var(--fw-ink-muted);
  font-size: 12px;
}

.metric-card--primary {
  border-color: #bfd5f7;
  background: var(--fw-brand-soft);
}

.metric-card--success {
  border-color: #b8e4cf;
  background: var(--fw-success-soft);
}

.metric-card--warning {
  border-color: #f3d4a7;
  background: var(--fw-warning-soft);
}
</style>
