"""Start the normal app against an explicitly selected local database."""
import argparse
from dataclasses import replace
from pathlib import Path
import socket
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.main import create_app
import uvicorn

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--database',type=Path,required=True)
    p.add_argument('--storage',type=Path,required=True)
    p.add_argument('--port',type=int,default=8774)
    args=p.parse_args()
    settings=replace(Settings.from_env(),database_path=args.database.resolve(),storage_path=args.storage.resolve(),
        autonomous_enabled=True,agent_loop_enabled=False,monthly_agent_enabled=False,require_auth=False,environment='development')
    # Reserve the port before app initialization/lifespan can start any workers.
    # A supervised duplicate must fail without enqueueing work in the same ledger.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', args.port))
        listener.listen()
        config = uvicorn.Config(create_app(settings), host='127.0.0.1', port=args.port)
        uvicorn.Server(config).run(sockets=[listener])
