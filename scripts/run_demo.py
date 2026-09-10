from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope


if __name__ == "__main__":
    settings = Settings.from_env()
    app = create_app(settings)
    scope = Scope(tenant_id="demo-tenant", organization_id="demo-org", legal_entity_id="demo-legal-entity", ledger_id="demo-ledger", accounting_period_id="2026-03", baseline_id="demo-baseline-2026-03")
    result = app.state.service.create_procurement_demo(scope, actor_id="demo", variant="normal")
    print(f"采购演示已建立：{result['group']['object_id']}，对账 {len(result['checks'])} 项")
