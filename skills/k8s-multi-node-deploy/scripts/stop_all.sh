#!/usr/bin/env bash
# Pool-wide cleanup: only for an explicitly authorized, dedicated node pool.
set -euo pipefail
usage() { echo 'Usage: stop_all.sh HOSTFILE [MAX_PARALLEL] [--execute --all-gpu-processes]'; }
(($#)) || { usage >&2; exit 2; }
[[ $1 != --help && $1 != -h ]] || { usage; exit 0; }
hostfile=$1; shift
parallel=32; execute=0; all_gpu=0
if (($#)) && [[ $1 != --* ]]; then parallel=$1; shift; fi
while (($#)); do
    case $1 in
        --execute) execute=1 ;;
        --all-gpu-processes) all_gpu=1 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done
[[ -f $hostfile && $parallel =~ ^[1-9][0-9]*$ ]] || { usage >&2; exit 2; }
((!execute || all_gpu)) || { echo 'Execution requires --all-gpu-processes for the reviewed dedicated pool.' >&2; exit 2; }
mapfile -t hosts < <(awk 'NF && $1 !~ /^#/ {print $1}' "$hostfile")
((${#hosts[@]})) || { echo 'Empty hostfile' >&2; exit 2; }
declare -A seen
for host in "${hosts[@]}"; do
    [[ $host =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ && ! ${seen[$host]+yes} ]] || { echo 'Invalid or duplicate host' >&2; exit 2; }
    seen[$host]=1
done
results=$(mktemp -d)
trap 'rm -f -- "$results"/*.result; rmdir -- "$results"' EXIT
batch=()
for host in "${hosts[@]}"; do
    (
        rc=0
        ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "$host" bash -s -- "$execute" >"$results/$host.result" 2>&1 <<'REMOTE' || rc=$?
set -euo pipefail
execute=$1
# A failed/unknown query must never be interpreted as an empty pool.
output=$(mthreads-gmi)
[[ $output == *'Processes:'* ]] || { echo 'GPU_QUERY_FORMAT_UNKNOWN'; exit 1; }
pids=$(awk '/^Processes:/ {active=1; next} active && /^[0-9]+[[:space:]]+[0-9]+/ {print $2}' <<< "$output" | sort -u)
[[ -n $pids ]] || { echo 'no_gpu_process'; exit 0; }
rc=0
for pid in $pids; do
    [[ $pid =~ ^[0-9]+$ && $pid -gt 1 ]] || { rc=1; continue; }
    if ((execute)); then
        if kill -0 "$pid" 2>/dev/null; then
            if kill -9 "$pid"; then echo "killed: $pid"; else echo "FAILED: $pid"; rc=1; fi
        else
            echo "exited_or_inaccessible: $pid"
            rc=1
        fi
    else
        echo "would_kill: $pid"
    fi
done
exit "$rc"
REMOTE
        printf 'EXIT_CODE=%s\n' "$rc" >>"$results/$host.result"
    ) &
    batch+=("$!")
    if ((${#batch[@]} >= parallel)); then
        for pid in "${batch[@]}"; do wait "$pid"; done
        batch=()
    fi
done
for pid in "${batch[@]}"; do wait "$pid"; done
rc=0
for host in "${hosts[@]}"; do
    printf '%s: ' "$host"
    cat "$results/$host.result"
    if ! grep -qx 'EXIT_CODE=0' "$results/$host.result"; then rc=1; fi
done
exit "$rc"
