-- 来源版式库：AI 或人工确认一次，之后同版式的文件确定性解析，不再调用模型。
-- 版式只描述"字段在第几列、空值怎么写、金额怎么表达"，绝不存放任何金额、主体或账号，
-- 因此 PLATFORM 级可以跨租户共享而不泄露客户数据。
CREATE TABLE IF NOT EXISTS source_profiles (
  profile_id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  document_kind TEXT NOT NULL,
  scope_level TEXT NOT NULL CHECK (scope_level IN ('PLATFORM','TENANT','ENTITY')),
  tenant_id TEXT,
  legal_entity_id TEXT,
  label TEXT NOT NULL,
  mapping_json TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('SEED','AGENT','HUMAN')),
  confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
  hit_count INTEGER NOT NULL DEFAULT 0,
  confirmed_by TEXT,
  confirmed_at TEXT,
  created_at TEXT NOT NULL,
  retired_at TEXT,
  CHECK (scope_level <> 'PLATFORM' OR (tenant_id IS NULL AND legal_entity_id IS NULL)),
  CHECK (scope_level <> 'TENANT'   OR (tenant_id IS NOT NULL AND legal_entity_id IS NULL)),
  CHECK (scope_level <> 'ENTITY'   OR (tenant_id IS NOT NULL AND legal_entity_id IS NOT NULL))
);

-- 同一指纹在同一作用域内只保留一条生效版式。
CREATE UNIQUE INDEX IF NOT EXISTS source_profiles_unique_live ON source_profiles (
  fingerprint, document_kind, scope_level,
  COALESCE(tenant_id, ''), COALESCE(legal_entity_id, '')
) WHERE retired_at IS NULL;

CREATE INDEX IF NOT EXISTS source_profiles_lookup ON source_profiles (fingerprint, document_kind)
  WHERE retired_at IS NULL;
