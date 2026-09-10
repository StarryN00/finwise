"""Provision local identities explicitly; never accept passwords in command-line arguments."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import ROLES, create_user, grant_scope
from app.config import Settings
from app.db import Database
from app.ontology.contracts import Scope


def main():
    parser = argparse.ArgumentParser(description="本地操作人和精确 Scope 授权管理")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("--role", choices=sorted(ROLES), required=True)
    grant = sub.add_parser("grant-scope")
    grant.add_argument("username")
    grant.add_argument("--scope-file", type=Path, required=True, help="包含六段 Scope 的 JSON 文件")
    revoke = sub.add_parser("disable-user")
    revoke.add_argument("username")
    args = parser.parse_args()
    db = Database(Settings.from_env())
    db.initialize()
    if args.action == "create-user":
        password = getpass.getpass("密码（至少12字符）：")
        if password != getpass.getpass("再次输入密码："):
            parser.error("两次密码不同，未创建用户")
        create_user(db, args.username, password, args.role)
    elif args.action == "grant-scope":
        grant_scope(db, args.username, Scope.model_validate(json.loads(args.scope_file.read_text())))
    else:
        with db.connect() as con:
            con.execute("UPDATE auth_users SET enabled=0 WHERE user_id=?", (args.username,))
            con.execute("DELETE FROM auth_sessions WHERE user_id=?", (args.username,))
    print("操作完成；未更改业务对象。")


if __name__ == "__main__":
    main()
