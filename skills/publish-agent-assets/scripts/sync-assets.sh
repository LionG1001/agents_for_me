#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sync-assets.sh --type skill|mcp-doc --repository-root PATH --source PATH [--source PATH ...] [--update]
EOF
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

type=''
repository_root=''
update=false
sources=()
while (($#)); do
  case "$1" in
    --type) type=${2-}; shift 2 ;;
    --repository-root) repository_root=${2-}; shift 2 ;;
    --source) sources+=("${2-}"); shift 2 ;;
    --update) update=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ $type == skill || $type == mcp-doc ]] || die '--type must be skill or mcp-doc.'
[[ -n $repository_root ]] || die '--repository-root is required.'
((${#sources[@]} > 0)) || die 'At least one --source is required.'
[[ -d $repository_root/.git ]] || die "Repository root is not a Git checkout: $repository_root"
repository_root=$(realpath "$repository_root")

for source in "${sources[@]}"; do
  [[ -e $source ]] || die "Source does not exist: $source"
  source=$(realpath "$source")
  symlink=$(find "$source" -type l -print -quit 2>/dev/null || true)
  [[ -z $symlink ]] || die "Refusing to copy a source containing symbolic links: $source"

  if [[ $type == skill ]]; then
    [[ -d $source && -f $source/SKILL.md ]] || die "Skill source does not contain SKILL.md: $source"
    asset_name=$(basename "$source")
    [[ $asset_name =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || die "Skill directory must use lowercase kebab-case: $asset_name"
    destination=$repository_root/skills/$asset_name
  else
    [[ -f $source && $source == *.md ]] || die "MCP document must be a Markdown file: $source"
    asset_name=$(basename "$source")
    destination=$repository_root/docs/mcp/$asset_name
  fi

  [[ $source != "$(realpath -m "$destination")" ]] || die "Source and destination are the same path: $source"
  if [[ -e $destination ]] && ! $update; then
    die "Destination already exists. Review it, then rerun with --update: $destination"
  fi

  if [[ $type == skill ]]; then
    mkdir -p "$destination"
    cp -a "$source"/. "$destination"/
  else
    mkdir -p "$(dirname "$destination")"
    cp -a "$source" "$destination"
  fi
  printf "Synchronized %s '%s' to '%s'.\n" "$type" "$asset_name" "$destination"
done
