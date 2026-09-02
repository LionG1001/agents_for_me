#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: invoke-rsync-relay.sh check|list|upload|download [options]

Options:
  --local-path PATH      Upload source or existing download directory
  --remote-path PATH     Path below the configured module/base path
  --execute              Perform upload/download; otherwise use --dry-run
  --config PATH          Config file (default: ~/.config/rsync-relay-transfer/config.json)
  --rsync EXECUTABLE     Alternate rsync executable
EOF
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

(($# > 0)) || { usage >&2; exit 2; }
action=$1; shift
[[ $action == check || $action == list || $action == upload || $action == download ]] || die "Unknown action: $action"
local_path=''; remote_path=''; execute=false
config_path=${XDG_CONFIG_HOME:-$HOME/.config}/rsync-relay-transfer/config.json
rsync_executable='rsync'
while (($#)); do
  case "$1" in
    --local-path) local_path=${2-}; shift 2 ;;
    --remote-path) remote_path=${2-}; shift 2 ;;
    --execute) execute=true; shift ;;
    --config) config_path=${2-}; shift 2 ;;
    --rsync) rsync_executable=${2-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -f $config_path ]] || die "未找到中转站配置：$config_path"
[[ ! /$remote_path/ =~ /\.\./ ]] || die 'Remote path cannot contain a parent-directory segment.'
[[ $remote_path != *$'\n'* && $remote_path != *$'\r'* && $remote_path != *'?'* && $remote_path != *'#'* ]] || die 'Remote path contains a prohibited character.'

mapfile -d '' config_values < <(python3 - "$config_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
required = ("host", "port", "module", "user", "password_file")
missing = [name for name in required if not config.get(name)]
if missing:
    raise SystemExit("配置缺少字段：" + ", ".join(missing))
for name in (*required, "base_path"):
    sys.stdout.write(str(config.get(name, "")) + "\0")
PY
)
((${#config_values[@]} == 6)) || die '无法读取中转站配置。'
host=${config_values[0]}; port=${config_values[1]}; module=${config_values[2]}; relay_user=${config_values[3]}; password_file=${config_values[4]}; base_path=${config_values[5]}
[[ -f $password_file ]] || die '配置中指定的密码文件不存在。'

if ! rsync_path=$(command -v "$rsync_executable" 2>/dev/null); then
  printf '配置文件和密码文件存在。\nRsync 可执行文件：未找到\n'
  [[ $action == check ]] && exit 2
  exit 1
fi
if [[ $action == check ]]; then
  printf '配置文件和密码文件存在。\nRsync 可执行文件：%s\n' "$rsync_path"
  exit 0
fi

remote_suffix=${base_path#/}; remote_suffix=${remote_suffix%/}
trimmed_remote=${remote_path#/}
if [[ -n $trimmed_remote ]]; then
  remote_suffix=${remote_suffix:+$remote_suffix/}$trimmed_remote
fi
remote_uri="rsync://$relay_user@$host:$port/$module"
[[ -z $remote_suffix ]] || remote_uri+="/$remote_suffix"
common=(--password-file "$password_file" --human-readable)

case "$action" in
  list)
    exec "$rsync_path" "${common[@]}" "$remote_uri"
    ;;
  upload)
    [[ -n $local_path && -e $local_path ]] || die '上传操作必须提供存在的 --local-path。'
    local_path=$(realpath "$local_path")
    args=(-a --itemize-changes --partial "${common[@]}")
    $execute || args+=(--dry-run)
    exec "$rsync_path" "${args[@]}" -- "$local_path" "$remote_uri"
    ;;
  download)
    [[ -n $local_path && -d $local_path ]] || die '下载操作的 --local-path 必须是已存在的目录。'
    local_path=$(realpath "$local_path")
    args=(-a --itemize-changes --partial "${common[@]}")
    $execute || args+=(--dry-run)
    exec "$rsync_path" "${args[@]}" -- "$remote_uri" "$local_path"
    ;;
esac
