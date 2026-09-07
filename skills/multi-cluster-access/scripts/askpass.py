#!/usr/bin/env python3
"""Credential-free SSH_ASKPASS; match the complete registered account/host."""
import os
import re
import sys

prompt = ' '.join(sys.argv[1:]).lower()
path = ''
for role in ('BASTION', 'TARGET'):
    account = os.environ.get(f'MCA_{role}_MATCH', '').lower()
    # Do not send worker1's secret in response to a prompt for worker10.
    if account and re.search(r'(?<![\w.@-])' + re.escape(account) + r"(?=['\s:]|$)", prompt):
        path = os.environ.get(f'MCA_{role}_PASSWORD_FILE', '')
        break
if not path:
    raise SystemExit(1)
try:
    with open(path, encoding='utf-8') as stream:
        value = stream.read()
except OSError:
    raise SystemExit(1)
sys.stdout.write(value)
