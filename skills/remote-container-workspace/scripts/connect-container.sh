#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: connect-container.sh --host HOST --user USER --container NAME --workdir PATH [options]

Options:
  --port PORT             SSH port (default: 22)
  --identity FILE         SSH private key
  --command COMMAND       Run one command through sh -lc
  --interactive           Open an interactive container shell
  --shell SHELL           Interactive shell (default: bash)
  --password-env NAME     Read the SSH password from this process environment variable
  --dry-run               Print the generated SSH invocation without running it
  -h, --help              Show this help
EOF
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

shell_quote() {
  local value=$1
  printf "'%s'" "${value//\'/\'\"\'\"\'}"
}

host=''
user=''
port=22
container=''
workdir=''
identity=''
command=''
interactive=false
container_shell='bash'
password_env=''
dry_run=false

while (($#)); do
  case "$1" in
    --host) host=${2-}; shift 2 ;;
    --user) user=${2-}; shift 2 ;;
    --port) port=${2-}; shift 2 ;;
    --container) container=${2-}; shift 2 ;;
    --workdir) workdir=${2-}; shift 2 ;;
    --identity) identity=${2-}; shift 2 ;;
    --command) command=${2-}; shift 2 ;;
    --interactive) interactive=true; shift ;;
    --shell) container_shell=${2-}; shift 2 ;;
    --password-env) password_env=${2-}; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n $host ]] || die '--host is required.'
[[ -n $user ]] || die '--user is required.'
[[ -n $container ]] || die '--container is required.'
[[ -n $workdir && $workdir == /* ]] || die '--workdir must be an absolute path.'
[[ $port =~ ^[0-9]+$ ]] && ((port >= 1 && port <= 65535)) || die '--port must be between 1 and 65535.'
if $interactive && [[ -n $command ]]; then
  die '--interactive and --command cannot be used together.'
fi
command -v ssh >/dev/null || die 'ssh is not available in PATH.'

ssh_args=(
  -p "$port"
  -o StrictHostKeyChecking=accept-new
  -o NumberOfPasswordPrompts=1
)
if [[ -n $identity ]]; then
  [[ -f $identity ]] || die "Identity file does not exist: $identity"
  identity=$(realpath "$identity")
  ssh_args+=(-i "$identity")
fi

quoted_workdir=$(shell_quote "$workdir")
quoted_container=$(shell_quote "$container")
if $interactive; then
  quoted_shell=$(shell_quote "$container_shell")
  remote_command="docker exec -it -w $quoted_workdir $quoted_container $quoted_shell"
  ssh_args+=(-tt)
elif [[ -n $command ]]; then
  quoted_command=$(shell_quote "$command")
  remote_command="docker exec -w $quoted_workdir $quoted_container sh -lc $quoted_command"
else
  remote_command="docker exec -w $quoted_workdir $quoted_container pwd"
fi
ssh_args+=("$user@$host" "$remote_command")

if $dry_run; then
  printf 'ssh'
  printf ' %q' "${ssh_args[@]}"
  printf '\nUses password environment variable: %s\n' "$([[ -n $password_env ]] && printf yes || printf no)"
  exit 0
fi

if [[ -z $password_env ]]; then
  exec ssh "${ssh_args[@]}"
fi

[[ $password_env =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die '--password-env must be a valid environment variable name.'
password=${!password_env-}
[[ -n $password ]] || die "The process environment variable '$password_env' is empty or undefined."

askpass_path=$(mktemp "${TMPDIR:-/tmp}/rcw-askpass.XXXXXX")
cleanup() {
  if [[ -n ${askpass_path:-} && -f $askpass_path ]]; then
    rm -f -- "$askpass_path"
  fi
}
trap cleanup EXIT HUP INT TERM
cat >"$askpass_path" <<'EOF'
#!/usr/bin/env sh
printf '%s\n' "$RCW_ASKPASS_PASSWORD"
EOF
chmod 700 "$askpass_path"

RCW_ASKPASS_PASSWORD=$password \
SSH_ASKPASS=$askpass_path \
SSH_ASKPASS_REQUIRE=force \
DISPLAY=remote-container-workspace \
ssh "${ssh_args[@]}"
