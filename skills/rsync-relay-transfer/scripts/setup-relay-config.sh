#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup-relay-config.sh --host HOST --port PORT --module MODULE --user USER [options]

Options:
  --base-path PATH       Base path inside the rsync module
  --config-dir PATH      Config directory (default: ~/.config/rsync-relay-transfer)
EOF
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

relay_host=''; port=''; module=''; relay_user=''; base_path=''; config_dir=${XDG_CONFIG_HOME:-$HOME/.config}/rsync-relay-transfer
while (($#)); do
  case "$1" in
    --host) relay_host=${2-}; shift 2 ;;
    --port) port=${2-}; shift 2 ;;
    --module) module=${2-}; shift 2 ;;
    --user) relay_user=${2-}; shift 2 ;;
    --base-path) base_path=${2-}; shift 2 ;;
    --config-dir) config_dir=${2-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n $relay_host && -n $module && -n $relay_user ]] || die '--host, --module, and --user are required.'
[[ $port =~ ^[0-9]+$ ]] && ((port >= 1 && port <= 65535)) || die '--port must be between 1 and 65535.'
[[ ! $relay_host =~ [[:space:]/@:] && ! $module =~ [[:space:]/@:] && ! $relay_user =~ [[:space:]/@:] ]] || die 'Host, module, and user cannot contain whitespace or URI separators.'
[[ ! /$base_path/ =~ /\.\./ ]] || die 'Base path cannot contain a parent-directory segment.'

IFS= read -r -s -p '请输入 rsync 中转站密码: ' password
printf '\n' >&2
[[ -n $password ]] || die '密码不能为空。'

umask 077
mkdir -p "$config_dir"
config_dir=$(realpath "$config_dir")
password_file=$config_dir/password.txt
config_file=$config_dir/config.json
printf '%s\n' "$password" >"$password_file"
unset password
chmod 600 "$password_file"

python3 - "$config_file" "$relay_host" "$port" "$module" "$relay_user" "${base_path#/}" "$password_file" <<'PY'
import json
import sys

path, host, port, module, user, base_path, password_file = sys.argv[1:]
with open(path, "w", encoding="utf-8", newline="\n") as stream:
    json.dump({"host": host, "port": int(port), "module": module, "user": user,
               "base_path": base_path.rstrip("/"), "password_file": password_file},
              stream, ensure_ascii=False, indent=2)
    stream.write("\n")
PY
chmod 600 "$config_file"
printf '配置已写入：%s\n密码已保存到权限为 0600 的文件。\n' "$config_file"
