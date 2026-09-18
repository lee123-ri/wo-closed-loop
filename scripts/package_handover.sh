#!/usr/bin/env bash
# 将无密钥源码包与已校验的数据库快照组合为受控部署交接包。
set -euo pipefail

data_snapshot="${1:?用法: scripts/package_handover.sh <清场后数据库dump>}"
source_package="${2:?用法: scripts/package_handover.sh <源码包tar.gz>}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${project_root}/outputs"
bundle_name="wo-closed-loop-0.7.0-$(date +%Y%m%d)-deployment-handover.tar.gz"

test -s "$data_snapshot"
test -s "$source_package"
pg_restore --list "$data_snapshot" >/dev/null
mkdir -p "$output_dir"
stage_dir="$(mktemp -d)"
trap 'rm -rf "$stage_dir"' EXIT
cp "$source_package" "$stage_dir/"
cp "$data_snapshot" "$stage_dir/"
tar -C "$stage_dir" -czf "$output_dir/$bundle_name" "$(basename "$source_package")" "$(basename "$data_snapshot")"
shasum -a 256 "$output_dir/$bundle_name" > "$output_dir/$bundle_name.sha256"
printf 'handover=%s\nsha256=%s\n' "$output_dir/$bundle_name" "$(cut -d ' ' -f 1 "$output_dir/$bundle_name.sha256")"
