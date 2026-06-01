<template>
  <section class="voucher-workbench-page">
    <div class="voucher-shell">
      <div class="voucher-header">
        <div>
          <h2 class="section-title">凭证生成工作台</h2>
          <p class="caption">按当前月度工作包生成、核对并确认会计凭证草稿。</p>
        </div>
        <div class="voucher-actions">
          <el-button :loading="isLoading" :disabled="!activePackage" @click="refreshVouchers">刷新</el-button>
          <el-button
            type="primary"
            :loading="isGenerating"
            :disabled="!activePackage"
            @click="preprocessVouchers"
          >
            AI 预处理
          </el-button>
        </div>
      </div>

      <div class="voucher-context">
        <div class="context-summary">
          <span class="context-eyebrow">当前操作主体</span>
          <strong>{{ activePackage?.company || '未选择企业' }}</strong>
          <span>{{ activePackage?.period || '未选择期间' }}</span>
        </div>
        <div class="context-meta">
          <el-tag size="small" type="info">{{ packageStatusLabel(activePackage?.status) }}</el-tag>
          <el-tag size="small" type="warning">工作包待确认 {{ activePackage?.pending ?? 0 }} 项</el-tag>
          <el-tag size="small" type="primary">凭证待确认 {{ pendingVoucherCount }} 张</el-tag>
        </div>
        <div class="context-controls">
          <label>
            <span>企业主体</span>
            <el-select
              v-model="selectedEnterpriseId"
              class="context-select"
              placeholder="选择企业主体"
              filterable
              @change="changeEnterprise"
            >
              <el-option
                v-for="item in enterpriseOptions"
                :key="item.enterpriseId"
                :label="item.company"
                :value="item.enterpriseId"
              />
            </el-select>
          </label>
          <label>
            <span>工作期间</span>
            <el-select
              v-model="selectedPeriodPackageId"
              class="context-select"
              placeholder="选择工作期间"
              :disabled="!selectedEnterpriseId || !periodOptions.length"
              @change="changePackage"
            >
              <el-option
                v-for="item in periodOptions"
                :key="item.id"
                :label="item.period"
                :value="item.id"
              />
            </el-select>
          </label>
        </div>
      </div>

      <div class="voucher-ledger-summary" aria-label="当月整理摘要">
        <div>
          <span>资金处理</span>
          <strong>{{ ledgerSummary.bank_processed_count }}/{{ ledgerSummary.bank_total_count }}</strong>
          <small>未处理 {{ ledgerSummary.bank_pending_count }} 条</small>
        </div>
        <div>
          <span>发票处理</span>
          <strong>{{ ledgerSummary.invoice_processed_count }}/{{ ledgerSummary.invoice_total_count }}</strong>
          <small>未处理 {{ ledgerSummary.invoice_pending_count }} 张</small>
        </div>
        <div>
          <span>凭证任务</span>
          <strong>{{ ledgerSummary.voucher_total_count }}</strong>
          <small>待确认 {{ ledgerSummary.pending_task_count }} 张</small>
        </div>
        <div>
          <span>差额补齐</span>
          <strong>{{ formatAmount(ledgerSummary.difference_total_amount) }}</strong>
          <small>需要人工核对</small>
        </div>
        <div>
          <span>单边补齐</span>
          <strong>{{ formatAmount(ledgerSummary.single_source_total_amount) }}</strong>
          <small>暂挂或待匹配</small>
        </div>
      </div>

      <div class="voucher-flow" aria-label="凭证处理流程">
        <div class="flow-step" :class="{ active: flowStep >= 1, done: vouchers.length > 0 }">
          <span>1</span>
          <strong>AI 预处理</strong>
          <small>{{ vouchers.length ? `已形成 ${vouchers.length} 张凭证任务` : '全量比对流水、发票和历史规则' }}</small>
        </div>
        <div class="flow-step" :class="{ active: flowStep >= 2, done: hasAiSuggestion }">
          <span>2</span>
          <strong>AI 推荐处理</strong>
          <small>{{ hasAiSuggestion ? '已给出摘要、科目、金额和判断说明' : '预处理后展示 AI 置信度和说明' }}</small>
        </div>
        <div class="flow-step" :class="{ active: flowStep >= 3, done: confirmedVoucherCount > 0 }">
          <span>3</span>
          <strong>人工确认</strong>
          <small>{{ pendingVoucherCount ? `待人工确认 ${pendingVoucherCount} 张` : '确认后生成正式凭证号' }}</small>
        </div>
      </div>

      <el-alert
        v-if="preprocessAudit"
        class="preprocess-alert"
        type="success"
        :closable="false"
        show-icon
      >
        <template #title>
          Kimi AI 预处理已完成
        </template>
        <template #default>
          模型：{{ preprocessAudit.model }}；流水 {{ preprocessAudit.input_bank_count }} 条；发票 {{ preprocessAudit.input_invoice_count }} 张；耗时 {{ preprocessAudit.duration_ms }}ms
        </template>
      </el-alert>

      <div class="voucher-layout">
        <div class="voucher-list-card source-workbench-card">
          <div class="list-header">
            <div>
              <strong>原始台账凭证整理</strong>
              <span>从资金流水或发票台账进入凭证核对</span>
            </div>
            <el-segmented
              v-model="activeLedgerTab"
              :options="[
                { label: '按资金流水整理', value: 'bank' },
                { label: '按发票台账整理', value: 'invoice' },
              ]"
              class="voucher-filter"
            />
          </div>

          <div v-if="activeLedgerTab === 'bank'" class="ledger-toolbar">
            <el-input v-model="bankLedgerKeyword" clearable placeholder="搜索日期、摘要、对方、金额" />
          </div>
          <div v-else class="ledger-toolbar invoice-ledger-toolbar">
            <el-select v-model="invoiceDirectionFilter" class="direction-filter" placeholder="发票方向">
              <el-option label="全部发票" value="all" />
              <el-option label="进项发票" value="INPUT" />
              <el-option label="销项发票" value="OUTPUT" />
            </el-select>
            <el-input v-model="invoiceLedgerKeyword" clearable placeholder="搜索发票号、对方、金额" />
          </div>

          <BankLedgerTable
            v-if="activeLedgerTab === 'bank'"
            :rows="filteredBankLedgerRows"
            :loading="isLoading"
            @row-select="selectBankLedgerRow"
          />
          <InvoiceLedgerTable
            v-else
            :rows="filteredInvoiceLedgerRows"
            :loading="isLoading"
            @row-select="selectInvoiceLedgerRow"
          />
        </div>

        <aside class="voucher-detail">
          <template v-if="selectedVoucher">
            <div class="detail-header">
              <div>
                <span class="detail-eyebrow">{{ selectedVoucher.voucher_number || '未编号' }}</span>
                <h3>{{ selectedVoucher.summary || '未填写摘要' }}</h3>
                <p>请按顺序核对 AI 推荐、异常提示和分录金额，再执行人工确认。</p>
              </div>
              <el-tag :type="statusTagType(selectedVoucher)" size="small">{{ statusLabel(selectedVoucher) }}</el-tag>
            </div>

            <dl class="detail-metrics">
              <div>
                <dt>AI 置信度</dt>
                <dd>{{ formatConfidence(selectedVoucher.ai_confidence) }}</dd>
              </div>
              <div>
                <dt>凭证日期</dt>
                <dd>{{ selectedVoucher.voucher_date || '-' }}</dd>
              </div>
            </dl>

            <div class="source-section">
              <div class="source-title">
                <strong>第 1 步：原始数据</strong>
                <span>先核对来源，再判断 AI 推荐是否合理</span>
              </div>

              <div v-if="hasSourceData" class="source-grid">
                <section v-if="sourceData.source_group_type" class="source-card source-card-wide source-group-card">
                  <strong>组合来源</strong>
                  <p>{{ sourceGroupTypeLabel(sourceData.source_group_type) }}</p>
                </section>

                <section
                  v-for="(transaction, index) in sourceBankTransactions"
                  :key="transaction.id || `bank-${index}`"
                  class="source-card"
                >
                  <strong>银行流水{{ sourceBankTransactions.length > 1 ? ` ${index + 1}` : '' }}</strong>
                  <dl>
                    <div>
                      <dt>交易日期</dt>
                      <dd class="matching-field">{{ transaction.transaction_date || '-' }}</dd>
                    </div>
                    <div>
                      <dt>流水摘要</dt>
                      <dd>{{ transaction.summary || '-' }}</dd>
                    </div>
                    <div>
                      <dt>对方户名</dt>
                      <dd class="matched-value">{{ transaction.counterparty_name || '-' }}</dd>
                    </div>
                    <div>
                      <dt>借方金额</dt>
                      <dd class="matched-value">{{ formatAmount(transaction.debit_amount) }}</dd>
                    </div>
                    <div>
                      <dt>贷方金额</dt>
                      <dd class="matched-value">{{ formatAmount(transaction.credit_amount) }}</dd>
                    </div>
                    <div>
                      <dt>余额</dt>
                      <dd>{{ transaction.balance ? formatAmount(transaction.balance) : '-' }}</dd>
                    </div>
                  </dl>
                </section>

                <section
                  v-for="(invoice, index) in sourceInvoices"
                  :key="invoice.id || `invoice-${index}`"
                  class="source-card"
                >
                  <strong>发票信息{{ sourceInvoices.length > 1 ? ` ${index + 1}` : '' }}</strong>
                  <dl>
                    <div>
                      <dt>发票方向</dt>
                      <dd>{{ invoiceDirectionLabel(invoice.invoice_direction) }}</dd>
                    </div>
                    <div>
                      <dt>发票号码</dt>
                      <dd>{{ invoice.invoice_number || '-' }}</dd>
                    </div>
                    <div>
                      <dt>开票日期</dt>
                      <dd class="matching-field">{{ invoice.invoice_date || '-' }}</dd>
                    </div>
                    <div>
                      <dt>销售方</dt>
                      <dd class="matched-value">{{ invoiceSellerName(invoice) }}</dd>
                    </div>
                    <div>
                      <dt>购买方</dt>
                      <dd class="matched-value">{{ invoiceBuyerName(invoice) }}</dd>
                    </div>
                    <div>
                      <dt>价税合计</dt>
                      <dd class="matched-value">{{ formatAmount(invoice.total_amount) }}</dd>
                    </div>
                  </dl>
                </section>

                <section v-if="missingSourceTreatment" class="source-card source-card-wide treatment-card">
                  <div class="treatment-card-header">
                    <div>
                      <strong>{{ missingSourceTreatment.title }}</strong>
                      <p>{{ missingSourceTreatment.description }}</p>
                    </div>
                    <el-tag type="warning" size="small">{{ missingSourceTreatment.treatmentType }}</el-tag>
                  </div>
                  <dl>
                    <div>
                      <dt>建议处理</dt>
                      <dd class="matched-value">{{ missingSourceTreatment.treatmentType }}</dd>
                    </div>
                    <div>
                      <dt>借方科目</dt>
                      <dd>{{ treatmentSubjectName(treatmentForm.debit_account_code) }}</dd>
                    </div>
                    <div>
                      <dt>贷方科目</dt>
                      <dd>{{ treatmentSubjectName(treatmentForm.credit_account_code) }}</dd>
                    </div>
                    <div>
                      <dt>建议原因</dt>
                      <dd>{{ missingSourceTreatment.reason }}</dd>
                    </div>
                  </dl>
                  <div v-if="isTreatmentFormOpen" class="treatment-form">
                    <label>
                      <span>处理方式</span>
                      <el-select v-model="treatmentForm.treatment_type" placeholder="选择处理方式">
                        <el-option
                          v-for="option in treatmentTypeOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </label>
                    <label>
                      <span>借方科目</span>
                      <el-select v-model="treatmentForm.debit_account_code" filterable placeholder="选择借方科目">
                        <el-option
                          v-for="option in treatmentSubjectOptions"
                          :key="`debit-${option.code}`"
                          :label="`${option.code} ${option.name}`"
                          :value="option.code"
                        />
                      </el-select>
                    </label>
                    <label>
                      <span>贷方科目</span>
                      <el-select v-model="treatmentForm.credit_account_code" filterable placeholder="选择贷方科目">
                        <el-option
                          v-for="option in treatmentSubjectOptions"
                          :key="`credit-${option.code}`"
                          :label="`${option.code} ${option.name}`"
                          :value="option.code"
                        />
                      </el-select>
                    </label>
                    <label class="treatment-form-wide">
                      <span>摘要</span>
                      <el-input v-model="treatmentForm.summary" placeholder="填写凭证摘要" />
                    </label>
                    <label class="treatment-form-wide">
                      <span>判断依据</span>
                      <el-input
                        v-model="treatmentForm.note"
                        type="textarea"
                        :rows="2"
                        placeholder="记录为什么采用或调整这个处理方式"
                      />
                    </label>
                  </div>
                  <div class="treatment-actions">
                    <el-button size="small" @click="openRematchDialog">重新匹配{{ missingSourceTreatment.missingLabel }}</el-button>
                    <el-button size="small" @click="toggleTreatmentForm">
                      {{ isTreatmentFormOpen ? '收起调整' : '调整处理方式' }}
                    </el-button>
                    <el-button
                      v-if="isTreatmentFormOpen"
                      size="small"
                      type="primary"
                      :loading="isApplyingTreatment"
                      @click="applyTreatmentAdjustment"
                    >
                      保存处理方式
                    </el-button>
                  </div>
                </section>

                <section
                  v-for="(match, index) in sourceMatches"
                  :key="match.id || `match-${index}`"
                  class="source-card source-card-wide"
                >
                  <strong>匹配记录{{ sourceMatches.length > 1 ? ` ${index + 1}` : '' }}</strong>
                  <dl>
                    <div>
                      <dt>匹配方式</dt>
                      <dd>{{ matchMethodLabel(match.match_method) }}</dd>
                    </div>
                    <div>
                      <dt>匹配置信度</dt>
                      <dd>{{ formatConfidence(match.confidence) }}</dd>
                    </div>
                    <div>
                      <dt>确认状态</dt>
                      <dd>{{ matchStatusLabel(match.confirmation_status) }}</dd>
                    </div>
                    <div>
                      <dt>匹配说明</dt>
                      <dd>{{ match.explanation || '-' }}</dd>
                    </div>
                  </dl>
                </section>
              </div>

              <p v-else class="source-empty">暂无原始数据，请重新执行 AI 预处理或检查来源记录。</p>
            </div>

            <div class="ai-reason">
              <strong>第 2 步：AI 推荐说明</strong>
              <p>{{ selectedVoucher.ai_reason || '暂无说明' }}</p>
            </div>

            <div v-if="validationErrors.length" class="validation-errors">
              <strong>异常提示</strong>
              <p>{{ validationErrorLabels.join('；') }}</p>
            </div>

            <el-table :data="selectedEntries" size="small" stripe>
              <el-table-column label="方向" width="80">
                <template #default="{ row }">{{ directionLabel(row.direction) }}</template>
              </el-table-column>
              <el-table-column prop="account_code" label="科目编码" width="110" />
              <el-table-column prop="account_name" label="科目名称" min-width="140" show-overflow-tooltip />
              <el-table-column label="金额" width="120" align="right">
                <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
              </el-table-column>
            </el-table>

            <div class="detail-actions">
              <span>第 3 步：人工确认后生成正式凭证号</span>
              <el-button
                v-if="canReopenVoucher"
                size="large"
                :loading="isReopening"
                @click="reopenVoucher"
              >
                {{ reopenButtonLabel }}
              </el-button>
              <el-button
                size="large"
                :loading="isLoadingRematch"
                :disabled="rematchDisabled"
                @click="openRematchDialog"
              >
                重新匹配
              </el-button>
              <el-button
                size="large"
                :loading="isRejecting"
                :disabled="rejectDisabled"
                @click="rejectVoucher"
              >
                标记不正确
              </el-button>
              <el-button
                type="primary"
                size="large"
                :loading="isConfirming"
                :disabled="confirmDisabled"
                @click="confirmVoucher"
              >
                确认凭证
              </el-button>
            </div>
          </template>
          <el-empty v-else description="选择一张凭证查看分录与 AI 说明" />
        </aside>
      </div>
    </div>

    <el-dialog
      v-model="rematchDialogVisible"
      title="重新匹配凭证来源"
      width="min(1280px, 92vw)"
      class="rematch-dialog"
    >
      <div class="rematch-intro">
        <strong>{{ selectedVoucher?.summary || '当前凭证' }}</strong>
        <span>选择正确的流水或发票后，系统会重建这张凭证草稿，并保留原操作审计记录。</span>
      </div>

      <el-segmented v-model="rematchMode" :options="rematchModeOptions" class="rematch-mode" />

      <div v-if="rematchPairPreview" class="rematch-pair-preview">
        <strong>新配对预览</strong>
        <span>{{ rematchPairPreview }}</span>
      </div>

      <div class="rematch-panels" :class="rematchPanelClass" v-loading="isLoadingRematch">
        <section v-if="showRematchInvoicePanel">
          <div class="rematch-panel-title">
            <strong>候选发票</strong>
            <span>{{ rematchMode === 'both' ? '选择要重新配对的发票' : '保留当前银行流水，重选发票' }}</span>
          </div>
          <el-input
            v-model="rematchInvoiceSearch"
            class="rematch-search"
            clearable
            placeholder="搜索日期、对方、金额、发票号或理由"
          />
          <div class="rematch-table-wrap">
            <el-table
              :data="filteredRematchInvoiceCandidates"
              size="small"
              height="420"
              empty-text="暂无候选发票"
              highlight-current-row
              :row-class-name="rematchCandidateRowClass"
              @row-click="selectRematchInvoice"
            >
            <el-table-column width="48">
              <template #default="{ row }">
                <el-checkbox
                  :model-value="selectedRematchInvoiceIds.includes(`invoice:${row.id}`)"
                  :disabled="!isRematchCandidateSelectable(row)"
                  @click.stop
                  @change="toggleRematchInvoice(row)"
                >
                  &nbsp;
                </el-checkbox>
              </template>
            </el-table-column>
            <el-table-column prop="date" label="日期" width="104" />
            <el-table-column label="发票方向" width="92">
              <template #default="{ row }">{{ rematchCandidateDirectionLabel(row) }}</template>
            </el-table-column>
            <el-table-column label="对方名称" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <el-popover placement="right" width="320" trigger="hover">
                  <template #reference>
                    <span class="candidate-detail-trigger">{{ rematchCandidateCounterpartyLabel(row) }}</span>
                  </template>
                  <div class="rematchCandidatePopover">
                    <strong>发票明细</strong>
                    <dl>
                      <div><dt>发票方向</dt><dd>{{ row.detail?.invoice_direction || rematchCandidateDirectionLabel(row) }}</dd></div>
                      <div><dt>发票号码</dt><dd>{{ row.detail?.invoice_number || '-' }}</dd></div>
                      <div><dt>开票日期</dt><dd>{{ row.detail?.invoice_date || row.date || '-' }}</dd></div>
                      <div><dt>销售方</dt><dd>{{ row.detail?.seller_name || '-' }}</dd></div>
                      <div><dt>购买方</dt><dd>{{ row.detail?.buyer_name || '-' }}</dd></div>
                      <div><dt>不含税金额</dt><dd>{{ formatAmount(row.detail?.amount) }}</dd></div>
                      <div><dt>税额</dt><dd>{{ formatAmount(row.detail?.tax_amount) }}</dd></div>
                      <div><dt>价税合计</dt><dd>{{ formatAmount(row.detail?.total_amount ?? row.amount) }}</dd></div>
                      <div><dt>推荐理由</dt><dd>{{ row.reason || '-' }}</dd></div>
                    </dl>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="候选状态" width="112">
              <template #default="{ row }">
                <el-tag :type="rematchCandidateStatusTag(row)" size="small">
                  {{ rematchCandidateStatusLabel(row) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="金额" width="112" align="right">
              <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
            </el-table-column>
            <el-table-column prop="score" label="评分" width="72" />
            <el-table-column prop="reason" label="推荐理由" min-width="130" show-overflow-tooltip />
            </el-table>
          </div>
        </section>

        <section v-if="showRematchBankPanel">
          <div class="rematch-panel-title">
            <strong>候选流水</strong>
            <span>{{ rematchMode === 'both' ? '选择要重新配对的银行流水' : '保留当前发票，重选银行流水' }}</span>
          </div>
          <el-input
            v-model="rematchBankSearch"
            class="rematch-search"
            clearable
            placeholder="搜索日期、对方、金额、发票号或理由"
          />
          <div class="rematch-table-wrap">
            <el-table
              :data="filteredRematchBankCandidates"
              size="small"
              height="420"
              empty-text="暂无候选流水"
              highlight-current-row
              :row-class-name="rematchCandidateRowClass"
              @row-click="selectRematchBank"
            >
            <el-table-column width="48">
              <template #default="{ row }">
                <el-checkbox
                  :model-value="selectedRematchBankIds.includes(`bank:${row.id}`)"
                  :disabled="!isRematchCandidateSelectable(row)"
                  @click.stop
                  @change="toggleRematchBank(row)"
                >
                  &nbsp;
                </el-checkbox>
              </template>
            </el-table-column>
            <el-table-column prop="date" label="日期" width="104" />
            <el-table-column label="收付方向" width="92">
              <template #default="{ row }">{{ rematchCandidateDirectionLabel(row) }}</template>
            </el-table-column>
            <el-table-column label="交易对方" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <el-popover placement="left" width="320" trigger="hover">
                  <template #reference>
                    <span class="candidate-detail-trigger">{{ rematchCandidateCounterpartyLabel(row) }}</span>
                  </template>
                  <div class="rematchCandidatePopover">
                    <strong>流水明细</strong>
                    <dl>
                      <div><dt>收付方向</dt><dd>{{ row.detail?.direction_label || rematchCandidateDirectionLabel(row) }}</dd></div>
                      <div><dt>交易日期</dt><dd>{{ row.detail?.transaction_date || row.date || '-' }}</dd></div>
                      <div><dt>流水摘要</dt><dd>{{ row.detail?.summary || row.description || '-' }}</dd></div>
                      <div><dt>交易对方</dt><dd>{{ row.detail?.counterparty_name || row.counterparty || '-' }}</dd></div>
                      <div><dt>对方账号</dt><dd>{{ row.detail?.counterparty_account || '-' }}</dd></div>
                      <div><dt>借方金额</dt><dd>{{ formatAmount(row.detail?.debit_amount) }}</dd></div>
                      <div><dt>贷方金额</dt><dd>{{ formatAmount(row.detail?.credit_amount) }}</dd></div>
                      <div><dt>余额</dt><dd>{{ row.detail?.balance ? formatAmount(row.detail.balance) : '-' }}</dd></div>
                      <div><dt>推荐理由</dt><dd>{{ row.reason || '-' }}</dd></div>
                    </dl>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
            <el-table-column label="候选状态" width="112">
              <template #default="{ row }">
                <el-tag :type="rematchCandidateStatusTag(row)" size="small">
                  {{ rematchCandidateStatusLabel(row) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="金额" width="112" align="right">
              <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
            </el-table-column>
            <el-table-column prop="score" label="评分" width="72" />
            <el-table-column prop="reason" label="推荐理由" min-width="130" show-overflow-tooltip />
            </el-table>
          </div>
        </section>
      </div>

      <template #footer>
        <el-button @click="rematchDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isApplyingRematch" :disabled="!canApplyRematch" @click="applyRematch">
          应用重新匹配
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import InvoiceLedgerTable from '../components/source-ledgers/InvoiceLedgerTable.vue'
import { sourceRowMatchesKeyword } from '../components/source-ledgers/ledgerFormatters'

const workspace = useWorkspaceStore()
const vouchers = ref([])
const ledgerSummary = ref(emptyLedgerSummary())
const selectedVoucherId = ref('')
const selectedEnterpriseId = ref('')
const selectedPeriodPackageId = ref('')
const activeLedgerTab = ref('bank')
const bankLedgerRows = ref([])
const invoiceLedgerRows = ref([])
const bankLedgerKeyword = ref('')
const invoiceLedgerKeyword = ref('')
const invoiceDirectionFilter = ref('all')
const preprocessAudit = ref(null)
const isLoading = ref(false)
const isGenerating = ref(false)
const isConfirming = ref(false)
const isRejecting = ref(false)
const isReopening = ref(false)
const isLoadingRematch = ref(false)
const isApplyingRematch = ref(false)
const isApplyingTreatment = ref(false)
const isTreatmentFormOpen = ref(false)
const rematchDialogVisible = ref(false)
const rematchCandidates = ref({ bank_candidates: [], invoice_candidates: [] })
const rematchMode = ref('replace-invoice')
const selectedRematchInvoiceIds = ref([])
const selectedRematchBankIds = ref([])
const rematchInvoiceSearch = ref('')
const rematchBankSearch = ref('')
const treatmentForm = ref({
  treatment_type: '',
  summary: '',
  debit_account_code: '',
  credit_account_code: '',
  note: '',
})
let voucherLoadRequestId = 0
let preprocessRequestId = 0

const rematchModeOptions = [
  { label: '保留流水重选发票', value: 'replace-invoice' },
  { label: '保留发票重选流水', value: 'replace-bank' },
  { label: '两边都重选', value: 'both' },
]
const treatmentSubjectOptions = [
  { code: '1002', name: '银行存款' },
  { code: '1122', name: '应收账款' },
  { code: '1123', name: '预付账款' },
  { code: '1221', name: '其他应收款' },
  { code: '2202', name: '应付账款' },
  { code: '2203', name: '预收账款' },
  { code: '2241', name: '其他应付款' },
  { code: '5001', name: '主营业务收入' },
  { code: '560203', name: '服务费' },
  { code: '560301', name: '手续费' },
]
const treatmentTypeOptions = [
  { label: '预收账款暂挂', value: '预收账款暂挂' },
  { label: '预付账款暂挂', value: '预付账款暂挂' },
  { label: '应收账款挂账', value: '应收账款挂账' },
  { label: '应付账款挂账', value: '应付账款挂账' },
  { label: '往来款暂挂', value: '往来款暂挂' },
  { label: '费用支出', value: '费用支出' },
  { label: '收入确认', value: '收入确认' },
]

const activePackage = computed(() => workspace.activePackage)
const activePackageId = computed(() => activePackage.value?.id || '')
const enterpriseOptions = computed(() => {
  const seen = new Set()
  const options = []
  for (const item of workspace.workPackages) {
    if (!item.enterpriseId || seen.has(item.enterpriseId)) continue
    seen.add(item.enterpriseId)
    options.push({ enterpriseId: item.enterpriseId, company: item.company })
  }
  return options
})
const periodOptions = computed(() =>
  workspace.workPackages.filter((item) => item.enterpriseId === selectedEnterpriseId.value),
)
const selectedVoucher = computed(() => vouchers.value.find((item) => item.id === selectedVoucherId.value) || null)
const selectedEntries = computed(() => selectedVoucher.value?.entries || [])
const sourceData = computed(() => normalizeSourceData(selectedVoucher.value?.source_data ?? selectedVoucher.value?.sourceData))
const sourceBankTransaction = computed(() => sourceData.value.bank_transaction || null)
const sourceBankTransactions = computed(() => {
  if (Array.isArray(sourceData.value.bank_transactions)) return sourceData.value.bank_transactions
  return sourceBankTransaction.value ? [sourceBankTransaction.value] : []
})
const sourceInvoice = computed(() => sourceData.value.invoice || null)
const sourceInvoices = computed(() => {
  if (Array.isArray(sourceData.value.invoices)) return sourceData.value.invoices
  return sourceInvoice.value ? [sourceInvoice.value] : []
})
const sourceMatch = computed(() => sourceData.value.match || null)
const sourceMatches = computed(() => {
  if (Array.isArray(sourceData.value.matches)) return sourceData.value.matches
  return sourceMatch.value ? [sourceMatch.value] : []
})
const sourceInvoiceSellerName = computed(() =>
  invoiceSellerName(sourceInvoice.value),
)
const sourceInvoiceBuyerName = computed(() =>
  invoiceBuyerName(sourceInvoice.value),
)
const hasSourceData = computed(() =>
  Boolean(sourceBankTransactions.value.length || sourceInvoices.value.length || sourceMatches.value.length),
)
const missingSourceTreatment = computed(() => {
  if (!selectedVoucher.value) return null
  const hasBank = sourceBankTransactions.value.length > 0
  const hasInvoice = sourceInvoices.value.length > 0
  if (hasBank && !hasInvoice) {
    const transaction = sourceBankTransactions.value[0]
    const isReceipt = Number(transaction?.credit_amount || 0) > 0
    return {
      title: '缺失发票，建议会计处理',
      missingLabel: '发票',
      description: isReceipt ? '银行收款暂未匹配到销项发票，可先按预收或往来款处理。' : '银行付款暂未匹配到进项发票，可先按预付或往来款处理。',
      treatmentType: existingTreatment.value?.treatment_type || (isReceipt ? '预收账款暂挂' : '预付账款暂挂'),
      reason: existingTreatment.value?.note || selectedVoucher.value.ai_reason || (isReceipt ? '银行收款暂无匹配发票，先按预收账款暂挂。' : '银行付款暂无匹配发票，先按预付账款暂挂。'),
    }
  }
  if (hasInvoice && !hasBank) {
    const invoice = sourceInvoices.value[0]
    const isOutput = invoice?.invoice_direction === 'OUTPUT'
    return {
      title: '缺失流水，建议会计处理',
      missingLabel: '流水',
      description: isOutput ? '销项发票暂未匹配到银行收款，可先按应收账款挂账。' : '进项发票暂未匹配到银行付款，可先按应付账款挂账。',
      treatmentType: existingTreatment.value?.treatment_type || (isOutput ? '应收账款挂账' : '应付账款挂账'),
      reason: existingTreatment.value?.note || selectedVoucher.value.ai_reason || (isOutput ? '销项发票暂无匹配流水，先按应收账款挂账。' : '进项发票暂无匹配流水，先按应付账款挂账。'),
    }
  }
  return null
})
const existingTreatment = computed(() => sourceData.value.accounting_treatment || null)
const validationErrors = computed(() => selectedVoucher.value?.validation_errors || [])
const validationErrorLabels = computed(() => validationErrors.value.map(validationErrorLabel))
const rematchInvoiceCandidates = computed(() => rematchCandidates.value.invoice_candidates || [])
const rematchBankCandidates = computed(() => rematchCandidates.value.bank_candidates || [])
const filteredRematchInvoiceCandidates = computed(() =>
  filterRematchCandidates(rematchInvoiceCandidates.value, rematchInvoiceSearch.value),
)
const filteredRematchBankCandidates = computed(() =>
  filterRematchCandidates(rematchBankCandidates.value, rematchBankSearch.value),
)
const showRematchInvoicePanel = computed(() => rematchMode.value === 'replace-invoice' || rematchMode.value === 'both')
const showRematchBankPanel = computed(() => rematchMode.value === 'replace-bank' || rematchMode.value === 'both')
const rematchPanelClass = computed(() =>
  showRematchInvoicePanel.value && showRematchBankPanel.value ? 'rematch-panels-dual' : 'rematch-panels-single',
)
const selectedRematchInvoices = computed(() =>
  rematchInvoiceCandidates.value.filter((item) => selectedRematchInvoiceIds.value.includes(`invoice:${item.id}`)),
)
const selectedRematchBanks = computed(() =>
  rematchBankCandidates.value.filter((item) => selectedRematchBankIds.value.includes(`bank:${item.id}`)),
)
const isManyToManyRematch = computed(() => selectedRematchInvoiceIds.value.length > 1 && selectedRematchBankIds.value.length > 1)
const canApplyRematch = computed(() => {
  if (isManyToManyRematch.value) return false
  if (rematchMode.value === 'replace-invoice') return selectedRematchInvoiceIds.value.length > 0
  if (rematchMode.value === 'replace-bank') return selectedRematchBankIds.value.length > 0
  return selectedRematchInvoiceIds.value.length > 0 && selectedRematchBankIds.value.length > 0
})
const rematchPairPreview = computed(() => {
  const invoices = selectedRematchInvoices.value
  const banks = selectedRematchBanks.value
  if (isManyToManyRematch.value) {
    return '当前只支持一对多或多对一重新匹配，请减少其中一侧的选择。'
  }
  if (rematchMode.value === 'replace-invoice' && invoices.length) {
    return `保留当前流水，改配${invoices.length}张发票，合计${formatAmount(sumCandidateAmounts(invoices))}。`
  }
  if (rematchMode.value === 'replace-bank' && banks.length) {
    return `保留当前发票，改配${banks.length}笔银行流水，合计${formatAmount(sumCandidateAmounts(banks))}。`
  }
  if (rematchMode.value === 'both' && invoices.length && banks.length) {
    const invoiceTotal = sumCandidateAmounts(invoices)
    const bankTotal = sumCandidateAmounts(banks)
    const amountMatch = Number(invoiceTotal) === Number(bankTotal) ? '金额一致' : '金额不一致'
    return `${banks.length}笔流水 + ${invoices.length}张发票，${amountMatch}，流水合计${formatAmount(bankTotal)}，发票合计${formatAmount(invoiceTotal)}。`
  }
  return ''
})
const confirmedVoucherCount = computed(() => vouchers.value.filter((voucher) => isConfirmed(voucher)).length)
const pendingVoucherCount = computed(() =>
  vouchers.value.filter((voucher) => !isConfirmed(voucher) && !isRejected(voucher) && !(voucher.validation_errors || []).length)
    .length,
)
const hasAiSuggestion = computed(() =>
  vouchers.value.some((voucher) => voucher.ai_confidence !== null && voucher.ai_confidence !== undefined),
)
const flowStep = computed(() => {
  if (confirmedVoucherCount.value > 0 || pendingVoucherCount.value > 0) return 3
  if (hasAiSuggestion.value) return 2
  if (vouchers.value.length) return 1
  return 0
})
const confirmDisabled = computed(() => {
  if (!selectedVoucher.value) return true
  return isConfirmed(selectedVoucher.value) || isRejected(selectedVoucher.value) || validationErrors.value.length > 0
})
const rejectDisabled = computed(() => {
  if (!selectedVoucher.value) return true
  return isConfirmed(selectedVoucher.value) || isRejected(selectedVoucher.value)
})
const canReopenVoucher = computed(() => {
  if (!selectedVoucher.value) return false
  return isConfirmed(selectedVoucher.value) || isRejected(selectedVoucher.value)
})
const reopenButtonLabel = computed(() => (isConfirmed(selectedVoucher.value) ? '撤销确认' : '恢复待确认'))
const rematchDisabled = computed(() => {
  if (!selectedVoucher.value) return true
  return isConfirmed(selectedVoucher.value)
})

const filteredBankLedgerRows = computed(() =>
  bankLedgerRows.value.filter((row) =>
    sourceRowMatchesKeyword(row, bankLedgerKeyword.value, [
      'transaction_date',
      'summary',
      'direction_label',
      'counterparty_name',
      'transaction_amount',
      'matching_status_label',
      'voucher_status_label',
    ]),
  ),
)

const filteredInvoiceLedgerRows = computed(() =>
  invoiceLedgerRows.value.filter((row) => {
    if (invoiceDirectionFilter.value !== 'all' && row.invoice_direction !== invoiceDirectionFilter.value) return false
    return sourceRowMatchesKeyword(row, invoiceLedgerKeyword.value, [
      'invoice_direction_label',
      'invoice_number',
      'invoice_date',
      'counterparty_role',
      'counterparty_name',
      'total_amount',
      'matching_status_label',
      'voucher_status_label',
    ])
  }),
)

watch(
  activePackage,
  (packageItem) => {
    const packageId = packageItem?.id || ''
    selectedEnterpriseId.value = packageItem?.enterpriseId || ''
    selectedPeriodPackageId.value = packageId
    if (!packageId) {
      voucherLoadRequestId += 1
      clearVouchers()
      return
    }
    loadVouchers(packageId)
  },
  { immediate: true },
)

watch(rematchMode, (mode) => {
  if (mode === 'replace-invoice') selectedRematchBankIds.value = []
  if (mode === 'replace-bank') selectedRematchInvoiceIds.value = []
})

watch(selectedVoucher, () => {
  isTreatmentFormOpen.value = false
  resetTreatmentForm()
})

async function changeEnterprise(enterpriseId) {
  if (!enterpriseId) return
  const currentPeriod = activePackage.value?.period
  const nextPackage =
    workspace.workPackages.find((item) => item.enterpriseId === enterpriseId && item.period === currentPeriod) ||
    workspace.workPackages.find((item) => item.enterpriseId === enterpriseId)
  if (!nextPackage || nextPackage.id === activePackageId.value) return
  await changePackage(nextPackage.id)
}

async function changePackage(packageId) {
  if (!packageId || packageId === activePackageId.value) return
  try {
    await workspace.selectPackage(packageId)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '切换工作包失败')
  }
}

async function refreshVouchers() {
  const didRefresh = await loadVouchers(activePackageId.value)
  if (didRefresh) {
    ElMessage.success(`凭证列表已刷新，共 ${vouchers.value.length} 张`)
  }
  return didRefresh
}

async function loadVouchers(packageId = activePackageId.value) {
  if (!packageId) {
    voucherLoadRequestId += 1
    clearVouchers()
    ElMessage.warning('请先选择企业主体和工作期间')
    return false
  }
  const requestId = ++voucherLoadRequestId
  isLoading.value = true
  try {
    const [voucherResponse, summaryResponse] = await Promise.all([
      api.vouchers.list(packageId),
      api.sourceLedgers.summary(packageId),
    ])
    if (isStaleVoucherLoad(requestId, packageId)) return false
    vouchers.value = normalizeVoucherList(voucherResponse.data)
    ledgerSummary.value = normalizeLedgerSummary(summaryResponse.data)
    keepSelection()
    await loadSourceLedgers(packageId, requestId)
    return true
  } catch (error) {
    if (isStaleVoucherLoad(requestId, packageId)) return false
    clearVouchers()
    ElMessage.error(error?.response?.data?.detail || error?.message || '凭证列表加载失败')
    return false
  } finally {
    if (!isStaleVoucherLoad(requestId, packageId)) {
      isLoading.value = false
    }
  }
}

async function loadSourceLedgers(packageId, requestId) {
  const [bankLedgerResult, invoiceLedgerResult] = await Promise.allSettled([
    api.sourceLedgers.bank(packageId),
    api.sourceLedgers.invoices(packageId),
  ])
  if (isStaleVoucherLoad(requestId, packageId)) return false
  if (bankLedgerResult.status === 'fulfilled') {
    bankLedgerRows.value = bankLedgerResult.value.data || []
  }
  if (invoiceLedgerResult.status === 'fulfilled') {
    invoiceLedgerRows.value = invoiceLedgerResult.value.data || []
  }
  const failedResult = [bankLedgerResult, invoiceLedgerResult].find((result) => result.status === 'rejected')
  if (failedResult) {
    ElMessage.warning(
      failedResult.reason?.response?.data?.detail ||
        failedResult.reason?.message ||
        '部分原始台账加载失败，已保留当前凭证列表',
    )
    return false
  }
  return true
}

async function preprocessVouchers() {
  const packageId = activePackageId.value
  if (!packageId) {
    ElMessage.warning('请先选择企业主体和工作期间')
    return
  }
  const requestId = ++preprocessRequestId
  isGenerating.value = true
  preprocessAudit.value = null
  try {
    const response = await api.vouchers.preprocess(packageId)
    if (isStalePreprocess(requestId, packageId)) return
    preprocessAudit.value = response.data?.audit || null
    const generatedVouchers = normalizeVoucherList(response.data)
    const createdVoucherCount = Number(response.data?.created_vouchers ?? generatedVouchers.length)
    await workspace.loadWorkspace(packageId)
    if (isStalePreprocess(requestId, packageId)) return
    const didLoadCurrentPackage = await loadVouchers(packageId)
    if (!didLoadCurrentPackage || isStalePreprocess(requestId, packageId)) return
    selectGeneratedVoucher(generatedVouchers)
    ElMessage.success(`AI 预处理完成，本次新增 ${createdVoucherCount} 张凭证任务`)
  } catch (error) {
    if (isStalePreprocess(requestId, packageId)) return
    ElMessage.error(error?.response?.data?.detail || error?.message || 'AI 预处理失败')
  } finally {
    if (!isStalePreprocess(requestId, packageId)) {
      isGenerating.value = false
    }
  }
}

async function confirmVoucher() {
  if (!selectedVoucher.value || confirmDisabled.value) return
  const voucherId = selectedVoucher.value.id
  const packageId = activePackageId.value
  isConfirming.value = true
  try {
    await api.vouchers.confirm(voucherId, { confirmed_by: 'operator' })
    await workspace.loadWorkspace(packageId)
    await loadVouchers(packageId)
    selectNextPendingVoucher(voucherId)
    ElMessage.success('凭证已确认')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '凭证确认失败')
  } finally {
    isConfirming.value = false
  }
}

async function rejectVoucher() {
  if (!selectedVoucher.value || rejectDisabled.value) return
  const voucherId = selectedVoucher.value.id
  const packageId = activePackageId.value
  isRejecting.value = true
  try {
    await api.vouchers.reject(voucherId, { rejected_by: 'operator', reason: '人工复核判定凭证不正确' })
    await workspace.loadWorkspace(packageId)
    await loadVouchers(packageId)
    selectNextPendingVoucher(voucherId)
    ElMessage.warning('凭证已标记为不正确')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '凭证驳回失败')
  } finally {
    isRejecting.value = false
  }
}

async function reopenVoucher() {
  if (!selectedVoucher.value || !canReopenVoucher.value) return
  const voucherId = selectedVoucher.value.id
  const packageId = activePackageId.value
  const reason = isConfirmed(selectedVoucher.value) ? '撤销确认后继续核对' : '恢复待确认后继续处理'
  isReopening.value = true
  try {
    const response = await api.vouchers.reopen(voucherId, { reopened_by: 'operator', reason })
    await workspace.loadWorkspace(packageId)
    await loadVouchers(packageId)
    selectedVoucherId.value = response.data?.id || voucherId
    ElMessage.success('凭证已恢复为待确认')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '凭证恢复失败')
  } finally {
    isReopening.value = false
  }
}

function resetTreatmentForm() {
  const treatment = existingTreatment.value
  const debitEntry = selectedEntries.value.find((entry) => entry.direction === 'DEBIT' || entry.direction === 'debit')
  const creditEntry = selectedEntries.value.find((entry) => entry.direction === 'CREDIT' || entry.direction === 'credit')
  treatmentForm.value = {
    treatment_type: treatment?.treatment_type || missingSourceTreatment.value?.treatmentType || '',
    summary: treatment?.summary || selectedVoucher.value?.summary || '',
    debit_account_code: treatment?.debit_account_code || debitEntry?.account_code || '',
    credit_account_code: treatment?.credit_account_code || creditEntry?.account_code || '',
    note: treatment?.note || '',
  }
}

function toggleTreatmentForm() {
  if (!isTreatmentFormOpen.value) resetTreatmentForm()
  isTreatmentFormOpen.value = !isTreatmentFormOpen.value
}

async function applyTreatmentAdjustment() {
  if (!selectedVoucher.value) return
  const voucherId = selectedVoucher.value.id
  const packageId = activePackageId.value
  isApplyingTreatment.value = true
  try {
    const response = await api.vouchers.adjustTreatment(voucherId, treatmentForm.value)
    await workspace.loadWorkspace(packageId)
    await loadVouchers(packageId)
    selectedVoucherId.value = response.data?.id || voucherId
    isTreatmentFormOpen.value = false
    ElMessage.success('会计处理方式已更新')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '处理方式保存失败')
  } finally {
    isApplyingTreatment.value = false
  }
}

async function openRematchDialog() {
  if (!selectedVoucher.value || rematchDisabled.value) return
  const voucherId = selectedVoucher.value.id
  rematchMode.value = 'replace-invoice'
  selectedRematchInvoiceIds.value = []
  selectedRematchBankIds.value = []
  rematchInvoiceSearch.value = ''
  rematchBankSearch.value = ''
  rematchDialogVisible.value = true
  isLoadingRematch.value = true
  try {
    const response = await api.vouchers.rematchCandidates(voucherId)
    if (selectedVoucher.value?.id !== voucherId) return
    rematchCandidates.value = response.data || { bank_candidates: [], invoice_candidates: [] }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '重新匹配候选加载失败')
    rematchDialogVisible.value = false
  } finally {
    isLoadingRematch.value = false
  }
}

function selectRematchInvoice(row) {
  toggleRematchInvoice(row)
}

function selectRematchBank(row) {
  toggleRematchBank(row)
}

function toggleRematchInvoice(row) {
  if (!isRematchCandidateSelectable(row)) return
  selectedRematchInvoiceIds.value = toggleSelection(selectedRematchInvoiceIds.value, `invoice:${row.id}`)
}

function toggleRematchBank(row) {
  if (!isRematchCandidateSelectable(row)) return
  selectedRematchBankIds.value = toggleSelection(selectedRematchBankIds.value, `bank:${row.id}`)
}

function toggleSelection(values, value) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

async function applyRematch() {
  if (!selectedVoucher.value || !canApplyRematch.value) return
  const voucherId = selectedVoucher.value.id
  const packageId = activePackageId.value
  const payload = rematchPayload()
  isApplyingRematch.value = true
  try {
    const response = await api.vouchers.rematch(voucherId, payload)
    await workspace.loadWorkspace(packageId)
    await loadVouchers(packageId)
    selectedVoucherId.value = response.data?.id || voucherId
    rematchDialogVisible.value = false
    ElMessage.success('凭证已重新匹配')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '重新匹配失败')
  } finally {
    isApplyingRematch.value = false
  }
}

function rematchPayload() {
  const payload = {}
  if ((rematchMode.value === 'replace-invoice' || rematchMode.value === 'both') && selectedRematchInvoiceIds.value.length) {
    payload.invoice_ids = selectedRematchInvoiceIds.value.map((item) => item.split(':')[1])
  }
  if ((rematchMode.value === 'replace-bank' || rematchMode.value === 'both') && selectedRematchBankIds.value.length) {
    payload.bank_transaction_ids = selectedRematchBankIds.value.map((item) => item.split(':')[1])
  }
  return payload
}

function normalizeVoucherList(payload) {
  if (Array.isArray(payload)) return payload.map(normalizeVoucher)
  if (Array.isArray(payload?.data)) return payload.data.map(normalizeVoucher)
  if (Array.isArray(payload?.vouchers)) return payload.vouchers.map(normalizeVoucher)
  if (payload?.id) return [normalizeVoucher(payload)]
  return []
}

function normalizeVoucher(voucher) {
  return {
    ...voucher,
    source_data: normalizeSourceData(voucher.source_data ?? voucher.sourceData),
  }
}

function normalizeSourceData(value) {
  if (!value) return {}
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return {}
    }
  }
  return value
}

function invoiceRawValue(invoice, keys) {
  const rawRow = invoice?.raw_row_data || invoice?.rawRowData || {}
  for (const key of keys) {
    const value = rawRow[key]
    if (value !== null && value !== undefined && String(value).trim() !== '') return String(value)
  }
  return ''
}

function invoiceSellerName(invoice) {
  return invoice?.seller_name || invoiceRawValue(invoice, ['销方名称', '销售方名称', '销售方']) || '-'
}

function invoiceBuyerName(invoice) {
  return invoice?.buyer_name || invoiceRawValue(invoice, ['购买方名称', '购方名称', '购买方']) || '-'
}

function isStaleVoucherLoad(requestId, packageId) {
  return requestId !== voucherLoadRequestId || packageId !== activePackageId.value
}

function isStalePreprocess(requestId, packageId) {
  return requestId !== preprocessRequestId || packageId !== activePackageId.value
}

function selectGeneratedVoucher(generatedVouchers) {
  const generatedIds = generatedVouchers.map((voucher) => voucher.id).filter(Boolean)
  const nextVoucher = vouchers.value.find((voucher) => generatedIds.includes(voucher.id)) || vouchers.value[0]
  selectedVoucherId.value = nextVoucher?.id || ''
}

function keepSelection() {
  if (vouchers.value.some((voucher) => voucher.id === selectedVoucherId.value)) return
  selectedVoucherId.value = vouchers.value[0]?.id || ''
}

function selectBankLedgerRow(row) {
  selectVoucherFromLedgerRow(row, '资金流水')
}

function selectInvoiceLedgerRow(row) {
  selectVoucherFromLedgerRow(row, '发票')
}

function selectVoucherFromLedgerRow(row, sourceLabel) {
  const linkedVoucherId = firstLinkedVoucherId(row)
  if (linkedVoucherId) {
    selectedVoucherId.value = linkedVoucherId
    return
  }
  ElMessage.warning(`${sourceLabel}暂未生成凭证任务，请先点击 AI 预处理`)
}

function firstLinkedVoucherId(row) {
  const links = row?.linked_vouchers || []
  const pending = links.find((item) => item.status === 'PENDING_CONFIRMATION')
  return pending?.id || links[0]?.id || ''
}

function selectNextPendingVoucher(previousVoucherId) {
  const previousIndex = vouchers.value.findIndex((voucher) => voucher.id === previousVoucherId)
  const orderedVouchers = [
    ...vouchers.value.slice(Math.max(previousIndex + 1, 0)),
    ...vouchers.value.slice(0, Math.max(previousIndex + 1, 0)),
  ]
  const nextVoucher = orderedVouchers.find(
    (voucher) => !isConfirmed(voucher) && !isRejected(voucher) && !(voucher.validation_errors || []).length,
  )
  selectedVoucherId.value = nextVoucher?.id || previousVoucherId
}

function clearVouchers() {
  preprocessRequestId += 1
  vouchers.value = []
  ledgerSummary.value = emptyLedgerSummary()
  bankLedgerRows.value = []
  invoiceLedgerRows.value = []
  preprocessAudit.value = null
  selectedVoucherId.value = ''
}

function emptyLedgerSummary() {
  return {
    bank_total_count: 0,
    bank_processed_count: 0,
    bank_pending_count: 0,
    invoice_total_count: 0,
    invoice_processed_count: 0,
    invoice_pending_count: 0,
    voucher_total_count: 0,
    pending_task_count: 0,
    difference_total_amount: 0,
    single_source_total_amount: 0,
  }
}

function normalizeLedgerSummary(value) {
  return { ...emptyLedgerSummary(), ...(value || {}) }
}

function isConfirmed(voucher) {
  if (isRejected(voucher)) return false
  return voucher.status === 'CONFIRMED' || voucher.status === 'confirmed' || Boolean(voucher.confirmed_at)
}

function isRejected(voucher) {
  return voucher.status === 'REJECTED' || voucher.status === 'rejected'
}

function statusLabel(voucher) {
  if (isRejected(voucher)) return '已驳回'
  if ((voucher.validation_errors || []).length) return '异常'
  if (isConfirmed(voucher)) return '已确认'
  return '待确认'
}

function statusTagType(voucher) {
  if (isRejected(voucher)) return 'danger'
  if ((voucher.validation_errors || []).length) return 'danger'
  if (isConfirmed(voucher)) return 'success'
  return 'warning'
}

function packageStatusLabel(value) {
  const labels = {
    PENDING_IMPORT: '待导入',
    PENDING_CONFIRMATION: '待确认',
    CONFIRMED: '已确认',
    COMPLETED: '已完成',
    READY: '已就绪',
    DATA_INSUFFICIENT: '数据不足',
    NOT_STARTED: '未开始',
    REJECTED: '已驳回',
  }
  return labels[value] || value || '未选择工作包'
}

function validationErrorLabel(value) {
  const labels = {
    DEBIT_CREDIT_NOT_EQUAL: '借贷金额不平',
    SUBJECT_NOT_ENABLED: '科目未启用',
    SUBJECT_NOT_LEAF: '必须使用末级科目',
    SUBJECT_NOT_FOUND: '科目不存在',
    MISSING_SUBJECT: '科目不存在',
    ZERO_AMOUNT: '分录金额不能为 0',
    DATE_OUT_OF_PERIOD: '凭证日期不在当前会计期间',
    OPERATOR_REJECTED: '人工复核判定不正确',
    SOURCE_REASSIGNED: '来源已被其他凭证重新匹配',
  }
  return labels[value] || value || '未知异常'
}

function confidenceTagType(value) {
  if (value === null || value === undefined || value === '') return 'info'
  const confidence = Number(value)
  if (Number.isNaN(confidence)) return 'info'
  if (confidence >= 85) return 'success'
  if (confidence >= 60) return 'warning'
  return 'danger'
}

function formatConfidence(value) {
  if (value === null || value === undefined || value === '') return '-'
  const confidence = Number(value)
  if (Number.isNaN(confidence)) return '-'
  return `${Math.round(confidence)}%`
}

function directionLabel(direction) {
  return direction === 'credit' || direction === 'CREDIT' ? '贷方' : '借方'
}

function invoiceDirectionLabel(value) {
  const labels = {
    OUTPUT: '销项发票',
    INPUT: '进项发票',
  }
  return labels[value] || value || '-'
}

function matchMethodLabel(value) {
  const labels = {
    AUTO_EXACT: '自动精确匹配',
    AUTO_FUZZY: '自动模糊匹配',
    MANUAL: '人工匹配',
    AI_GROUPED: 'AI 组合匹配',
    MANUAL_REMAP: '人工重新匹配',
  }
  return labels[value] || value || '-'
}

function sourceGroupTypeLabel(value) {
  const labels = {
    FULL_MATCH: '完全配对',
    DIFFERENCE_COMPLETION: '差额补齐',
    SINGLE_SOURCE: '单边补齐',
    HISTORICAL_REVIEW: '历史延续',
    BANK_ONLY: '单边补齐',
    INVOICE_ONLY: '单边补齐',
    ONE_INVOICE_MULTIPLE_BANK_TRANSACTIONS: '一张发票对应多笔银行流水',
    ONE_BANK_TRANSACTION_MULTIPLE_INVOICES: '一笔银行流水对应多张发票',
  }
  return labels[value] || value || '组合来源'
}

function matchStatusLabel(value) {
  const labels = {
    AUTO_CONFIRMED: '自动确认',
    CONFIRMED: '已确认',
    PENDING: '待确认',
    REJECTED: '已驳回',
  }
  return labels[value] || value || '-'
}

function filterRematchCandidates(candidates, keyword) {
  const query = String(keyword || '').trim().toLowerCase()
  if (!query) return candidates
  return candidates.filter((candidate) =>
    [
      candidate.date,
      candidate.counterparty,
      candidate.counterparty_role,
      candidate.direction_label,
      candidate.amount,
      candidate.description,
      candidate.reason,
      candidate.disabled_reason,
      rematchCandidateStatusLabel(candidate),
      ...Object.values(candidate.detail || {}),
    ]
      .filter((value) => value !== null && value !== undefined)
      .some((value) => String(value).toLowerCase().includes(query)),
  )
}

function rematchCandidateDirectionLabel(candidate) {
  return candidate?.direction_label || candidate?.detail?.direction_label || candidate?.detail?.invoice_direction || '-'
}

function rematchCandidateCounterpartyLabel(candidate) {
  const role = candidate?.counterparty_role ? `${candidate.counterparty_role}: ` : ''
  return `${role}${candidate?.counterparty || candidate?.detail?.counterparty_name || '-'}`
}

function treatmentSubjectName(code) {
  const subject = treatmentSubjectOptions.find((item) => item.code === code)
  return subject ? `${subject.code} ${subject.name}` : code || '-'
}

function sumCandidateAmounts(candidates) {
  return candidates.reduce((total, candidate) => total + Number(candidate.amount || 0), 0)
}

function isRematchCandidateSelectable(candidate) {
  return candidate?.is_selectable !== false && !candidate?.is_current && !candidate?.is_used
}

function rematchCandidateStatusLabel(candidate) {
  if (candidate?.is_current) return '当前使用'
  if (candidate?.is_used) return candidate.disabled_reason || '已占用'
  return '可选择'
}

function rematchCandidateStatusTag(candidate) {
  if (candidate?.is_current) return 'info'
  if (candidate?.is_used) return 'warning'
  return 'success'
}

function rematchCandidateRowClass({ row }) {
  return isRematchCandidateSelectable(row) ? '' : 'rematch-candidate-disabled'
}

function formatAmount(value) {
  const amount = Number(value)
  if (Number.isNaN(amount)) return '-'
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<style scoped>
.voucher-workbench-page {
  display: grid;
  gap: 16px;
}

.voucher-shell {
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.voucher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.voucher-header .caption {
  margin: 4px 0 0;
}

.voucher-context {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto minmax(360px, 480px);
  gap: 12px;
  align-items: end;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: var(--fw-surface-muted);
}

.context-summary {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.context-summary strong,
.context-summary span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-summary strong {
  font-size: 15px;
}

.context-summary span {
  color: var(--fw-ink-muted);
  font-size: 12px;
}

.context-eyebrow {
  color: var(--fw-brand);
  font-size: 12px;
  font-weight: 700;
}

.context-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.context-controls {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(140px, 0.7fr);
  gap: 10px;
}

.context-controls label {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.context-controls label > span {
  color: var(--fw-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.context-select {
  width: 100%;
}

.voucher-flow {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.voucher-ledger-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.voucher-ledger-summary > div {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: var(--fw-surface-muted);
}

.voucher-ledger-summary span,
.voucher-ledger-summary small {
  display: block;
  overflow: hidden;
  color: var(--fw-ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.voucher-ledger-summary strong {
  display: block;
  margin: 5px 0;
  color: var(--fw-ink);
  font-size: 18px;
}

.flow-step {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 2px 8px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: var(--fw-surface);
  color: var(--fw-ink-muted);
}

.flow-step span {
  display: inline-flex;
  grid-row: span 2;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: var(--fw-surface-muted);
  color: var(--fw-ink-soft);
  font-size: 12px;
  font-weight: 800;
}

.flow-step strong,
.flow-step small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flow-step strong {
  color: var(--fw-ink-soft);
}

.flow-step small {
  font-size: 12px;
}

.flow-step.active {
  border-color: #93c5fd;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px #bfdbfe;
}

.flow-step.active span {
  background: var(--fw-brand);
  color: #fff;
}

.flow-step.done strong {
  color: var(--fw-brand);
}

.voucher-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.voucher-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 16px;
  align-items: start;
}

.preprocess-alert {
  margin-bottom: 14px;
}

.voucher-list-card {
  min-width: 0;
}

.source-workbench-card {
  display: grid;
  gap: 10px;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.list-header strong,
.list-header span {
  display: block;
}

.list-header strong {
  color: var(--fw-ink);
  font-size: 14px;
}

.list-header span {
  margin-top: 2px;
  color: var(--fw-ink-muted);
  font-size: 12px;
}

.voucher-filter {
  flex: 0 0 auto;
}

.ledger-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  margin-bottom: 2px;
}

.invoice-ledger-toolbar {
  grid-template-columns: minmax(140px, 180px) minmax(0, 1fr);
}

.direction-filter {
  width: 100%;
}

.voucher-detail {
  min-width: 0;
  min-height: 420px;
  padding: 18px;
  border: 1px solid #bfdbfe;
  border-radius: var(--fw-radius);
  background: #f8fbff;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.detail-header h3 {
  margin: 4px 0 0;
  font-size: 18px;
}

.detail-header p {
  margin: 6px 0 0;
  color: var(--fw-ink-muted);
  font-size: 12px;
  line-height: 1.5;
}

.detail-eyebrow {
  color: var(--fw-text-muted);
  font-size: 12px;
}

.detail-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}

.detail-metrics div,
.ai-reason,
.source-section,
.source-card,
.validation-errors {
  padding: 10px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.detail-metrics dt {
  color: var(--fw-text-muted);
  font-size: 12px;
}

.detail-metrics dd {
  margin: 4px 0 0;
  font-weight: 700;
}

.ai-reason,
.source-section,
.validation-errors {
  margin-bottom: 14px;
}

.source-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.source-title span {
  color: var(--fw-text-muted);
  font-size: 12px;
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.source-card {
  min-width: 0;
}

.source-card strong {
  display: block;
  margin-bottom: 8px;
}

.source-card-wide {
  grid-column: 1 / -1;
}

.source-group-card {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.source-group-card p {
  margin: 0;
  color: var(--fw-brand);
  font-size: 12px;
  font-weight: 700;
}

.treatment-card {
  border-color: #fed7aa;
  background: #fff7ed;
}

.treatment-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.treatment-card-header p {
  margin: 4px 0 0;
  color: var(--fw-ink-muted);
  font-size: 12px;
  line-height: 1.5;
}

.treatment-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #fed7aa;
}

.treatment-form label {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.treatment-form label > span {
  color: var(--fw-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.treatment-form-wide {
  grid-column: 1 / -1;
}

.treatment-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.source-card dl {
  display: grid;
  gap: 6px;
  margin: 0;
}

.source-card > dl > div {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
}

.source-card dt {
  color: var(--fw-text-muted);
  font-size: 12px;
}

.source-card dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--fw-ink);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-card dd.matched-value,
.source-card dd.matching-field {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  min-height: 22px;
  padding: 2px 7px;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  background: #eff6ff;
  color: #1d4ed8;
}

.source-card dd.matching-field {
  border-color: #c7d2fe;
  background: #eef2ff;
  color: #3730a3;
}

.source-empty {
  margin: 0;
  color: var(--fw-text-muted);
  font-size: 12px;
}

.ai-reason p,
.validation-errors p {
  margin: 6px 0 0;
  color: var(--fw-text-muted);
  line-height: 1.6;
}

.validation-errors {
  border-color: var(--el-color-danger-light-5);
}

.detail-actions {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin: 16px -18px -18px;
  padding: 14px 18px;
  border-top: 1px solid #bfdbfe;
  border-radius: 0 0 var(--fw-radius) var(--fw-radius);
  background: #eff6ff;
}

.detail-actions span {
  margin-right: auto;
  color: var(--fw-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.rematch-intro {
  display: grid;
  gap: 4px;
  margin-bottom: 14px;
  color: var(--fw-ink-muted);
  font-size: 13px;
}

.rematch-intro strong {
  color: var(--fw-ink);
  font-size: 16px;
}

.rematch-mode {
  margin-bottom: 12px;
}

.rematch-pair-preview {
  display: grid;
  gap: 4px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #bfdbfe;
  border-radius: var(--fw-radius-sm);
  background: #eff6ff;
  color: var(--fw-ink-muted);
  font-size: 12px;
}

.rematch-pair-preview strong {
  color: var(--fw-brand);
  font-size: 13px;
}

.rematch-panels {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
}

.rematch-panels-dual {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.rematch-panels-single {
  grid-template-columns: minmax(0, 1fr);
}

.rematch-panel-title {
  display: grid;
  gap: 2px;
  margin-bottom: 8px;
}

.rematch-panel-title span {
  color: var(--fw-ink-muted);
  font-size: 12px;
}

.rematch-search {
  margin-bottom: 10px;
}

.rematch-table-wrap {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
}

.rematch-table-wrap :deep(.el-table) {
  min-width: 860px;
}

.candidate-detail-trigger {
  cursor: help;
  color: var(--fw-brand);
  font-weight: 700;
}

:global(.rematchCandidatePopover) {
  display: grid;
  gap: 8px;
  color: var(--fw-ink);
}

:global(.rematchCandidatePopover strong) {
  color: var(--fw-brand);
}

:global(.rematchCandidatePopover dl) {
  display: grid;
  gap: 6px;
  margin: 0;
}

:global(.rematchCandidatePopover div) {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 8px;
}

:global(.rematchCandidatePopover dt) {
  color: var(--fw-text-muted);
}

:global(.rematchCandidatePopover dd) {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 700;
}

:deep(.rematch-candidate-disabled) {
  color: var(--fw-text-muted);
  opacity: 0.62;
}

:deep(.rematch-candidate-disabled td) {
  background: #f8fafc !important;
}

@media (max-width: 1180px) {
  .voucher-context {
    grid-template-columns: 1fr;
  }

  .voucher-flow {
    grid-template-columns: 1fr;
  }

  .voucher-ledger-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .context-meta {
    justify-content: flex-start;
  }

  .context-controls {
    grid-template-columns: 1fr;
  }

  .voucher-layout {
    grid-template-columns: 1fr;
  }

  .rematch-panels {
    grid-template-columns: 1fr;
  }

  .list-header {
    align-items: flex-start;
    display: grid;
  }
}

@media (max-width: 760px) {
  .voucher-header,
  .voucher-actions {
    display: grid;
  }
}
</style>
