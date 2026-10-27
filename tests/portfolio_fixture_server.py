"""Disposable portfolio navigation fixture; only synthetic companies and a simulated analyst."""
import argparse
from pathlib import Path
import uvicorn
from operator_settings_fixture_server import build
from app.auth import grant_scope

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8798)
    args = parser.parse_args()
    app = build(args.root)
    previous = app.state.settings_fixture_scopes[0].model_copy(update={
        'accounting_period_id': '2026-02', 'baseline_id': 'settings-a-feb'})
    app.state.service.create_scope(previous)
    for user in ('settings-tester', 'settings-viewer'):
        grant_scope(app.state.database, user, previous)
    uvicorn.run(app, host='127.0.0.1', port=args.port)
