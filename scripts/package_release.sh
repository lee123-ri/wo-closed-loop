#!/usr/bin/env bash
# 生成不含凭据、缓存和本机数据的完整源码部署包。
set -euo pipefail

release_version="${1:-0.7.0}"
release_date="$(date +%Y%m%d)"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${project_root}/outputs"
package_name="wo-closed-loop-${release_version}-${release_date}"
stage_dir="$(mktemp -d)"
trap 'rm -rf "$stage_dir"' EXIT

mkdir -p "$output_dir"
git -C "$project_root" archive --format=tar --prefix="${package_name}/" HEAD | tar -xf - -C "$stage_dir"

# git archive 不含未跟踪但应交付的模板/文档；本项目的必要物料均受版本控制。
tar -C "$stage_dir" -czf "${output_dir}/${package_name}.tar.gz" "$package_name"
shasum -a 256 "${output_dir}/${package_name}.tar.gz" > "${output_dir}/${package_name}.tar.gz.sha256"
printf 'package=%s\nsha256=%s\n' \
  "${output_dir}/${package_name}.tar.gz" \
  "$(cut -d ' ' -f 1 "${output_dir}/${package_name}.tar.gz.sha256")"
