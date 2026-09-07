#!/usr/bin/env python3
"""Render an IPv4 hostfile from verified Deployment/ReplicaSet/Pod JSON snapshots."""
import argparse
import ipaddress
import json
import sys
from pathlib import Path


def owned_by(obj, uid):
    return any(o.get('uid') == uid and o.get('controller') is True
               for o in obj.get('metadata', {}).get('ownerReferences', []))


def matches(labels, selector):
    if any(labels.get(k) != v for k, v in selector.get('matchLabels', {}).items()):
        return False
    for requirement in selector.get('matchExpressions', []):
        key, op = requirement['key'], requirement['operator']
        values = requirement.get('values', [])
        if op == 'In':
            ok = key in labels and labels[key] in values
        elif op == 'NotIn':
            ok = key not in labels or labels[key] not in values
        elif op == 'Exists':
            ok = key in labels
        elif op == 'DoesNotExist':
            ok = key not in labels
        else:
            raise ValueError('Unsupported selector operator')
        if not ok:
            return False
    return True


def render(deployment, replicasets, pods, container, nodes, slots):
    if nodes < 1 or slots < 1:
        raise ValueError('nodes and slots must be positive')
    namespace = deployment['metadata']['namespace']
    uid = deployment['metadata']['uid']
    selector = deployment['spec']['selector']
    owners = {rs['metadata']['uid'] for rs in replicasets['items']
              if rs['metadata'].get('namespace') == namespace and owned_by(rs, uid)}
    selected = {}
    addresses = set()
    for pod in pods['items']:
        meta, spec, status = pod['metadata'], pod['spec'], pod.get('status', {})
        if meta.get('namespace') != namespace or meta.get('deletionTimestamp'):
            continue
        if not matches(meta.get('labels', {}), selector) or not any(owned_by(pod, owner) for owner in owners):
            continue
        if status.get('phase') != 'Running' or not any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in status.get('conditions', [])):
            continue
        target = next((c for c in spec.get('containers', []) if c['name'] == container), None)
        ready = next((c for c in status.get('containerStatuses', []) if c['name'] == container), None)
        if not target or not ready or not ready.get('ready'):
            continue
        if not spec.get('hostNetwork'):
            raise ValueError('Host-IP hostfile requires a verified hostNetwork workload')
        gpu_count = int(target.get('resources', {}).get('limits', {}).get('mthreads.com/gpu', 0))
        if gpu_count < slots:
            raise ValueError('Requested slots exceed container GPU limit')
        node = spec.get('nodeName')
        address = str(ipaddress.IPv4Address(status.get('hostIP')))
        if not node or node in selected or address in addresses:
            raise ValueError('Missing or duplicate node/host IP; reconcile rollout before selecting hosts')
        selected[node] = address
        addresses.add(address)
    if len(selected) < nodes:
        raise ValueError('Insufficient owned Running/Ready nodes')
    return ''.join(f'{address} slots={slots}\n' for address in sorted(addresses, key=ipaddress.IPv4Address)[:nodes])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('deployment', 'replicasets', 'pods'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--container', required=True)
    parser.add_argument('--nodes', type=int, required=True)
    parser.add_argument('--slots', type=int, required=True)
    args = parser.parse_args()
    try:
        snapshots = [json.loads(getattr(args, name).read_text()) for name in ('deployment', 'replicasets', 'pods')]
        print(render(*snapshots, args.container, args.nodes, args.slots), end='')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f'Hostfile rejected: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
