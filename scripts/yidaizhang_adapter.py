#!/usr/bin/env python3
"""Inspect/validate explicit 易代账 template and receipt profiles."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow direct execution from a checkout without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.yidaizhang import TemplateProfile, bind_receipt_to_manifest, export_voucher_file, inspect_template, load_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="FinWise 易代账文件适配器工具")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect-template")
    inspect.add_argument("path", type=Path)
    export = sub.add_parser("export")
    export.add_argument("--export-json", type=Path, required=True)
    export.add_argument("--scope-json", type=Path, required=True)
    export.add_argument("--template", type=Path, required=True)
    export.add_argument("--profile", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--manifest", type=Path, required=True)
    receipt = sub.add_parser("validate-receipt")
    receipt.add_argument("path", type=Path)
    receipt.add_argument("--profile", type=Path)
    receipt.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "inspect-template":
            value = inspect_template(args.path)
        elif args.command == "export":
            profile = TemplateProfile.from_dict(json.loads(args.profile.read_text(encoding="utf-8")))
            value = export_voucher_file(
                export=json.loads(args.export_json.read_text(encoding="utf-8")),
                scope=json.loads(args.scope_json.read_text(encoding="utf-8")),
                template_path=args.template,
                profile=profile,
                output_path=args.output,
                manifest_path=args.manifest,
            )
        else:
            profile = TemplateProfile.from_dict(json.loads(args.profile.read_text(encoding="utf-8"))) if args.profile else None
            value = load_receipt(args.path, profile=profile)
            if args.manifest:
                manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
                value = bind_receipt_to_manifest(value, manifest)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
