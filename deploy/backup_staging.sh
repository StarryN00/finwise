#!/usr/bin/env sh
set -eu

backup_dir="${1:?用法: backup_staging.sh /absolute/backup/directory}"
db_path="${FINWISE_DATABASE_PATH:-./data/finwise.db}"
storage_path="${FINWISE_STORAGE_PATH:-./data/artifacts}"
mkdir -p "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

if [ ! -f "$db_path" ]; then
  echo "数据库不存在: $db_path" >&2
  exit 2
fi
if [ ! -d "$storage_path" ]; then
  echo "原始资料目录不存在: $storage_path" >&2
  exit 2
fi

sqlite3 "$db_path" ".backup '$backup_dir/finwise-$timestamp.db'"
tar -czf "$backup_dir/artifacts-$timestamp.tar.gz" -C "$storage_path" .
printf '%s\n' "备份完成: $backup_dir/finwise-$timestamp.db" "$backup_dir/artifacts-$timestamp.tar.gz"
