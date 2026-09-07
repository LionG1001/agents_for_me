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
[[ $1 != --help && $1 != -h ]] || { usage; exit 0; }
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
[[ $remote_path != *'\'* ]] || die 'Use forward slashes in remote paths.'
[[ ! /$remote_path/ =~ /\.\./ ]] || die 'Remote path cannot contain a parent-directory segment.'
[[ $remote_path != *$'\n'* && $remote_path != *$'\r'* && $remote_path != *'?'* && $remote_path != *'#'* ]] || die 'Remote path contains a prohibited character.'

mapfile -d '' config_values < <(python3 - "$config_path" <<'PY'
import json
import sys
import re
import stat
from pathlib import Path

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
required = ("host", "port", "module", "user", "password_file")
missing = [name for name in required if not config.get(name)]
if missing:
    raise SystemExit("配置缺少字段：" + ", ".join(missing))
for name in ("host", "module", "user"):
    if not isinstance(config[name], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", config[name]):
        raise SystemExit("Invalid relay endpoint field: " + name)
if not isinstance(config["port"], int) or isinstance(config["port"], bool) or not 1 <= config["port"] <= 65535:
    raise SystemExit("Invalid relay port")
base = config.get("base_path", "")
if not isinstance(base, str) or ".." in base.split("/") or any(c in base for c in "\\\r\n?#\0"):
    raise SystemExit("Invalid relay base_path")
password_path = Path(config["password_file"])
if not password_path.is_absolute() or password_path.is_symlink() or not password_path.is_file():
    raise SystemExit("Password file must be an absolute regular file, not a symlink")
if password_path.stat().st_mode & 0o077:
    raise SystemExit("Password file must not be accessible to group/others")
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
    source_had_slash=false
    [[ $local_path != */ ]] || source_had_slash=true
    local_path=$(realpath "$local_path")
    if $source_had_slash && [[ -d $local_path ]]; then local_path+=/; fi
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
