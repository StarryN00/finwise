# Frontend UI Layout Guidelines

This document defines layout rules for FinWise operator pages. It exists to prevent clipped tables, hidden right-side content, raw enum values, and oversized columns.

## Scope

Apply these rules to all Vue 3 + Element Plus pages in `finwise-accounting/frontend`, especially:

- Management tables
- Monthly workbench pages
- Voucher, subject, rule, tax, report, and enterprise pages
- Any page with filters plus a data table

## Core Rules

### 1. Tables Must Never Clip Without Scroll

If a table can be wider than its panel, wrap it in a horizontal scroll container.

Required pattern:

```vue
<div class="table-scroll">
  <el-table :data="rows" class="compact-table" stripe>
    ...
  </el-table>
</div>
```

```css
.table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-color: var(--fw-brand) #eaf2ff;
  scrollbar-width: thin;
}

.table-scroll::-webkit-scrollbar {
  height: 12px;
}

.table-scroll::-webkit-scrollbar-track {
  background: #eaf2ff;
}

.table-scroll::-webkit-scrollbar-thumb {
  border: 2px solid #eaf2ff;
  border-radius: 999px;
  background: var(--fw-brand);
}

.compact-table {
  width: 100%;
  min-width: 760px;
}
```

Use a larger `min-width` only when the columns truly need it. The goal is visible, deliberate scrolling, not accidental horizontal overflow.

The table must also fill available width on desktop. Do not leave a narrow table floating on the left side of a wide panel.

### 2. Column Widths Must Match Content

Use fixed widths for predictable fields, and leave one non-critical text column flexible with `min-width` so the table can expand cleanly on wide screens.

| Field Type | Suggested Width |
| --- | ---: |
| Code / ID fragment | 100-130px |
| Date | 110-130px |
| Boolean tag | 76-100px |
| Status tag | 100-140px |
| Direction | 80-110px |
| Amount | 120-150px |
| Short Chinese name | 140-180px |
| Long company name / summary | 180-260px with tooltip |

Avoid this on management pages:

```vue
<el-table-column prop="name" label="科目名称" min-width="260" />
```

Prefer this when the name column can safely absorb extra space:

```vue
<el-table-column prop="name" label="科目名称" min-width="150" show-overflow-tooltip />
```

Use flexible `min-width` only for the one or two fields that are meant to absorb space, such as summaries or company names.

### 3. Raw Backend Enums Must Be Translated

Never display backend enum values such as `ASSET`, `LIABILITY`, `DEBIT`, `CREDIT`, `PENDING_CONFIRMATION`, or `PROFIT_LOSS` directly.

Required pattern:

```vue
<el-table-column label="类别" width="120">
  <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
</el-table-column>

<el-table-column label="余额方向" width="100">
  <template #default="{ row }">{{ balanceDirectionLabel(row.normal_balance) }}</template>
</el-table-column>
```

```js
function categoryLabel(value) {
  const labels = {
    ASSET: '资产',
    LIABILITY: '负债',
    EQUITY: '所有者权益',
    COST: '成本',
    REVENUE: '收入',
    EXPENSE: '费用',
    PROFIT_LOSS: '损益',
  }
  return labels[value] || value || '-'
}

function balanceDirectionLabel(value) {
  const labels = {
    DEBIT: '借方',
    CREDIT: '贷方',
  }
  return labels[value] || value || '-'
}
```

If the same enum appears on more than one page, move the formatter into a shared utility instead of duplicating it.

### 4. Filters And Actions Must Wrap Cleanly

Header action areas must not force the page wider than the viewport.

Recommended:

```css
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.page-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 760px) {
  .page-header,
  .page-actions {
    display: grid;
  }
}
```

### 5. Dense Workbench Pages Are Not Marketing Pages

FinWise is an internal operator system. Favor:

- Compact rows
- Clear column labels
- Stable table widths
- Visible filters
- No decorative card nesting
- No large empty columns caused by one oversized table field

Avoid:

- Giant hero-style panels
- One table column taking most of the page
- Hidden right-side operation columns
- English enum labels in Chinese business workflows

## Test Requirements

When adding or modifying a table page, add source-level assertions for:

- The horizontal scroll wrapper class, such as `table-scroll` or a page-specific equivalent.
- Chinese enum formatter calls, such as `categoryLabel(...)` or `statusLabel(...)`.
- Important column labels.
- API route strings when the page introduces new endpoints.

Example:

```js
expect(viewSource).toContain('subjects-table-scroll')
expect(viewSource).toContain('categoryLabel(row.category)')
expect(viewSource).toContain('balanceDirectionLabel(row.normal_balance)')
expect(viewSource).toContain("ASSET: '资产'")
expect(viewSource).toContain("DEBIT: '借方'")
```

## Review Checklist

Before completing a frontend table page, verify:

- Narrow the browser window to laptop split-screen width.
- Confirm right-side columns remain reachable by horizontal scroll.
- Confirm the page itself does not create invisible clipped content.
- Confirm all enum/status/direction fields are zh-CN.
- Confirm long names use tooltip or wrapping instead of stretching the layout.
- Run the relevant Vitest file.
- Run `npm run build` after structural layout changes.
