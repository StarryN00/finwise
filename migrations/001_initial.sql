CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ontology_objects (
  object_id TEXT NOT NULL,
  object_type TEXT NOT NULL,
  version INTEGER NOT NULL,
  scope_json TEXT NOT NULL,
  status TEXT NOT NULL,
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  PRIMARY KEY (object_id, version)
);

CREATE INDEX IF NOT EXISTS idx_objects_type_scope
  ON ontology_objects (object_type, scope_json, version);

CREATE TABLE IF NOT EXISTS relations (
  relation_id TEXT PRIMARY KEY,
  relation_type TEXT NOT NULL,
  from_type TEXT NOT NULL,
  from_id TEXT NOT NULL,
  from_version INTEGER NOT NULL,
  to_type TEXT NOT NULL,
  to_id TEXT NOT NULL,
  to_version INTEGER NOT NULL,
  scope_json TEXT NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_relations_scope
  ON relations (relation_type, scope_json, from_id, to_id);

CREATE TABLE IF NOT EXISTS commands (
  command_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL,
  target_id TEXT NOT NULL,
  target_version INTEGER NOT NULL,
  scope_json TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  status TEXT NOT NULL,
  request_json TEXT NOT NULL,
  effect_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  object_type TEXT,
  object_id TEXT,
  object_version INTEGER,
  scope_json TEXT NOT NULL,
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_runs (
  run_id TEXT PRIMARY KEY,
  scope_json TEXT NOT NULL,
  status TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  baseline_version INTEGER NOT NULL,
  rule_version TEXT NOT NULL,
  model_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  gateway_version TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  parent_run_id TEXT,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_checks (
  check_id TEXT PRIMARY KEY,
  scope_json TEXT NOT NULL,
  group_id TEXT NOT NULL,
  check_type TEXT NOT NULL,
  input_json TEXT NOT NULL,
  formula TEXT NOT NULL,
  tolerance TEXT NOT NULL,
  result TEXT NOT NULL,
  reason TEXT NOT NULL,
  check_version TEXT NOT NULL,
  executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_receipts (
  receipt_id TEXT PRIMARY KEY,
  export_id TEXT NOT NULL,
  package_id TEXT NOT NULL,
  voucher_version_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  received_at TEXT NOT NULL
);

