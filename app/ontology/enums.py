from __future__ import annotations

from enum import Enum


class ObjectType(str, Enum):
    SCOPE = "Scope"
    ACCOUNTING_BOOK = "AccountingBook"
    ACCOUNTING_PERIOD = "AccountingPeriod"
    BASELINE = "BaselineSnapshot"
    HISTORICAL_PREPARATION = "HistoricalPreparation"
    SOURCE_ARTIFACT = "SourceArtifact"
    FACT_RECORD = "FactRecord"
    BUSINESS_FACT = "BusinessFact"
    BUSINESS_EVENT = "BusinessEvent"
    PROCESSING_GROUP = "ProcessingGroup"
    PROCESSING_GROUP_REVISION = "ProcessingGroupRevision"
    EVIDENCE = "Evidence"
    DECISION = "Decision"
    RULE_CANDIDATE = "RuleCandidate"
    CONFIRMATION_CARD = "ConfirmationCard"
    RULE_CONFLICT = "RuleConflict"
    AGENT_SUGGESTION = "AgentSuggestion"
    MODEL_RUN = "ModelRun"
    RULE_INSTANCE = "RuleInstance"
    VOUCHER_PROPOSAL = "VoucherProposal"
    VOUCHER_DRAFT = "VoucherDraft"
    VOUCHER_VERSION = "VoucherVersion"
    DELIVERY_PACKAGE = "DeliveryPackage"
    EXPORT = "ExportCreated"
    EXTERNAL_RECEIPT = "ExternalReceipt"
    EFFECT = "EffectRecord"


class RelationType(str, Enum):
    DERIVED_FROM = "DERIVED_FROM"
    SUPPORTS = "SUPPORTS"
    MATCHES = "MATCHES"
    BELONGS_TO = "BELONGS_TO"
    APPLIES_TO = "APPLIES_TO"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    GENERATES = "GENERATES"
    VALIDATES = "VALIDATES"


class SourceDisposition(str, Enum):
    UNASSESSED = "UNASSESSED"
    ASSIGNED = "ASSIGNED"
    SPLIT = "SPLIT"
    DUPLICATE = "DUPLICATE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SUSPENSE = "SUSPENSE"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
