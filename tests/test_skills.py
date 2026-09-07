"""Offline behavioral regressions. No SSH, VPN, rsync or GPU service is contacted."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SKILLS = Path(os.environ.get('AUDIT_SKILLS_ROOT', ROOT / 'skills'))


def script(skill, name):
    return SKILLS / skill / 'scripts' / name


def load(skill, name):
    # Parsing tests do not need a PDF rendering backend.
    with patch.dict(sys.modules, {'pdfplumber': types.ModuleType('pdfplumber')}):
        spec = importlib.util.spec_from_file_location(name.replace('.', '_'), script(skill, name))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], text=True, capture_output=True, timeout=15, **kwargs)


def fake(path, body):
    path.write_text('#!/usr/bin/env python3\n' + body)
    path.chmod(0o700)


class Assets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        run(['git', 'init', '-q', self.repo])
        self.source = self.base / 'demo'
        self.source.mkdir()
        (self.source / 'SKILL.md').write_text('---\nname: demo\ndescription: Demonstrate a fixture\n---\n')

    def sync(self, *extra, source=None, repo=None):
        return run(['bash', script('publish-agent-assets', 'sync-assets.sh'), '--type', 'skill',
                    '--source', source or self.source, '--repository-root', repo or self.repo, *extra])

    def validate(self):
        return run(['bash', script('publish-agent-assets', 'validate-repository.sh'), self.repo])

    def test_destination_symlink_rejected(self):
        outside = self.base / 'outside'; outside.mkdir()
        (self.repo / 'skills').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_source_root_symlink_rejected(self):
        alias = self.base / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        self.assertNotEqual(self.sync(source=alias).returncode, 0)

    def test_skips_cache(self):
        cache = self.source / '__pycache__'; cache.mkdir(); (cache / 'x.pyc').write_bytes(b'cache')
        result = self.sync(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / 'skills/demo/__pycache__').exists())

    def test_refuses_secret_file_before_any_write(self):
        (self.source / '.env').write_text('fixture only')
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertFalse((self.repo / 'skills/demo').exists())

    def test_dry_run(self):
        result = self.sync('--dry-run'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / 'skills').exists())

    def test_update_keeps_destination_only_files(self):
        self.assertEqual(self.sync().returncode, 0)
        old = self.repo / 'skills/demo/keep.md'; old.write_text('keep')
        (self.source / 'new.md').write_text('new')
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual(self.sync('--update').returncode, 0)
        self.assertEqual(old.read_text(), 'keep')

    def test_worktree_checkout(self):
        run(['git', '-C', self.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '--allow-empty', '-qm', 'fixture'])
        tree = self.base / 'tree'
        result = run(['git', '-C', self.repo, 'worktree', 'add', '-q', '-b', 'test', tree])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sync(repo=tree).returncode, 0)

    def test_valid_repository(self):
        self.assertEqual(self.sync().returncode, 0)
        result = self.validate(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_yaml_rejected(self):
        self.sync()
        (self.repo / 'skills/demo/SKILL.md').write_text('---\nname: demo\ndescription: [unterminated\n---\n')
        self.assertNotEqual(self.validate().returncode, 0)

    def test_empty_block_description_rejected(self):
        self.sync()
        (self.repo / 'skills/demo/SKILL.md').write_text('---\nname: demo\ndescription: >-\n---\n')
        self.assertNotEqual(self.validate().returncode, 0)

    def test_angle_link_checked(self):
        self.sync(); (self.repo / 'README.md').write_text('[missing](<no such file.md>)\n')
        self.assertNotEqual(self.validate().returncode, 0)

    def test_extensionless_token_detected_without_echo(self):
        self.sync(); token = 'ghp_' + 'x' * 30
        (self.repo / 'leak').write_text(token)
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(token, result.stdout + result.stderr)


class Invoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load('organize-invoices', 'invoice_inventory.py')

    def inspect_text(self, text):
        with patch.object(self.mod, 'read_text', return_value=text), patch.object(self.mod, 'sha256', return_value='fixture'):
            return self.mod.inspect(Path('餐费.pdf'))

    def test_unlabelled_number_is_not_invoice_id(self):
        self.assertIsNone(self.inspect_text('银行账号 12345678901234567890')['invoice_number'])

    def test_multiple_labelled_numbers_need_review(self):
        self.assertIsNone(self.inspect_text('发票号码：12345678901234567890\n发票号码：22345678901234567890')['invoice_number'])

    def test_unlabelled_currency_is_not_total(self):
        self.assertIsNone(self.mod.extract_amount('单价 ￥12.00\n税额 ￥1.00'))

    def test_total_not_last_currency(self):
        self.assertEqual(str(self.mod.extract_amount('价税合计（小写）￥123.45\n备注 ￥1.00')), '123.45')

    def test_comma_total(self):
        self.assertEqual(str(self.mod.extract_amount('（小写）￥1,234.56')), '1234.56')

    def test_invalid_date_needs_review(self):
        self.assertIsNone(self.mod.extract_date('开票日期：2026年02月30日'))

    def test_unlabelled_date_is_not_issue_date(self):
        self.assertIsNone(self.mod.extract_date('订单日期：2026-09-01'))

    def test_filename_does_not_classify(self):
        self.assertEqual(self.mod.classify('办公文具', Path('餐饮服务.pdf')), '其他')

    def test_negative_total_needs_review(self):
        result = self.inspect_text('发票号码：12345678901234567890\n开票日期：2026年09月01日\n（小写）￥-12.00')
        self.assertIsNotNone(result['error'])

    def test_cli_uppercase_pdf_and_decimal_json(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'one.PDF'; path.write_bytes(b'fixture PDF placeholder')
            text='发票号码：12345678901234567890\n开票日期：2026年09月01日\n（小写）￥12.34'
            output=io.StringIO()
            with patch.object(self.mod, 'read_text', return_value=text), patch.object(sys, 'argv', ['inventory',td,'--json']), redirect_stdout(output):
                rc=self.mod.main()
            data=json.loads(output.getvalue())
            self.assertEqual(rc,0)
            self.assertEqual(data['汇总']['PDF数量'],1)
            self.assertEqual(data['明细'][0]['金额'],'12.34')

    def test_unreadable_file_does_not_abort_inventory(self):
        with patch.object(self.mod, 'read_text', side_effect=OSError('fixture')), patch.object(self.mod, 'sha256', side_effect=OSError('fixture')):
            self.assertIsNotNone(self.mod.inspect(Path('absent.pdf'))['error'])


def config():
    endpoint = {'host': 'worker.example.com', 'port': 22, 'username': 'dev', 'auth_mode': 'password', 'secret_ref': 'demo/dev'}
    return {'version': 2, 'clusters': {'demo': {'bastions': {'gateway': endpoint.copy()},
           'targets': {'worker': {**endpoint, 'bastion': 'gateway'}},
           'access_profiles': {'task-user': {'targets': {'worker': {}}}}}},
           'tasks': {'task': {'cluster': 'demo', 'target': 'worker', 'access_profile': 'task-user', 'container': 'app', 'workdir': '/workspace'}}}


class Cluster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load('multi-cluster-access', 'clusterctl.py')

    def test_documented_schema_loads(self):
        doc = (SKILLS / 'multi-cluster-access/references/registry.md').read_text()
        data = json.loads(re.search(r'```json\n(.*?)\n```', doc, re.S)[1])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'config.json'; path.write_text(json.dumps(data))
            with patch.dict(os.environ, {'CLUSTER_ACCESS_CONFIG': str(path)}):
                self.mod.load_config()

    def test_effective_profile_auth_validated(self):
        data = config(); data['clusters']['demo']['access_profiles']['task-user']['targets']['worker']['auth_mode'] = 'unknown'
        with self.assertRaises(ValueError): self.mod.endpoint(data, 'task')

    def test_option_like_username_rejected(self):
        data = config(); data['clusters']['demo']['targets']['worker']['username'] = '-oProxyCommand=bad'
        with self.assertRaises(ValueError): self.mod.validate_config(data)

    def test_profiles_do_not_mutate_base_identity(self):
        data = config(); before = copy.deepcopy(data)
        data['clusters']['demo']['access_profiles']['task-user']['targets']['worker']['username'] = 'alternate'
        _, _, target, _ = self.mod.endpoint(data, 'task')
        self.assertEqual(target['username'], 'alternate')
        self.assertEqual(data['clusters']['demo']['targets'], before['clusters']['demo']['targets'])

    def test_askpass_requires_complete_account(self):
        with tempfile.TemporaryDirectory() as td:
            secret = Path(td)/'secret'; secret.write_text('fixture-value')
            env = {**os.environ, 'MCA_BASTION_MATCH': 'dev@worker1', 'MCA_BASTION_PASSWORD_FILE': str(secret)}
            result = run([sys.executable, script('multi-cluster-access','askpass.py'), "dev@worker10's password:"], env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('fixture-value', result.stdout)
            result = run([sys.executable, script('multi-cluster-access','askpass.py'), "dev@worker1's password:"], env=env)
            self.assertEqual(result.stdout, 'fixture-value')

    def test_failed_vpn_start_stops_new_unit_and_removes_auth_file(self):
        with tempfile.TemporaryDirectory() as td:
            directory=Path(td); profile=directory/'vpn.conf'; profile.write_text('fixture')
            vpn={'profile':str(profile), 'server_name':'vpn.example.com', 'username':'demo', 'secret_ref':'fixture/vpn'}
            calls=[]
            def command(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 1 if 'is-active' in args else 0, '', '')
            original=tempfile.mkstemp
            def create(**kwargs):
                kwargs['dir']=directory
                return original(**kwargs)
            with patch.object(self.mod,'vpn_ready',return_value=False), patch.object(self.mod,'default_route_snapshot',return_value='default'), patch.object(self.mod,'dns_snapshot',return_value=('192.0.2.1',)), patch.object(self.mod,'get_secret',return_value='fixture'), patch.object(self.mod,'run',side_effect=command), patch.object(self.mod.tempfile,'mkstemp',side_effect=create):
                with self.assertRaises(RuntimeError): self.mod._start_vpn_locked('demo',{'vpn':vpn})
            stops=[args for args in calls if args[:3]==['sudo','systemctl','stop']]
            self.assertEqual(len(stops),2)
            self.assertEqual(list(directory.glob('mca-*')),[])

    def test_stop_failure_not_reported_success(self):
        def command(args, **kwargs):
            if kwargs.get('check'): raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 1, '', '')
        from contextlib import nullcontext
        with patch.object(self.mod, 'mutation_lock', return_value=nullcontext()), patch.object(self.mod, 'run', side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError): self.mod.stop_vpn('demo')


class Shell(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.bin = self.base / 'bin'; self.bin.mkdir()
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH']}

    def test_container_rejects_option_injection(self):
        result = run(['bash', script('remote-container-workspace','connect-container.sh'), '--host', 'worker.example.com', '--user', '-oProxyCommand=bad', '--container', 'app', '--workdir', '/workspace', '--dry-run'])
        self.assertNotEqual(result.returncode, 0)

    def test_container_quotes_apostrophe_and_command(self):
        import shlex
        result = run(['bash', script('remote-container-workspace','connect-container.sh'), '--host', 'worker.example.com', '--user', 'dev', '--container', 'app', '--workdir', "/workspace/a'b", '--command', 'echo "literal $HOME"', '--dry-run'])
        self.assertEqual(result.returncode, 0, result.stderr)
        # Bash %q output can contain $'...' escapes; let bash recover argv locally.
        fake(self.bin / 'ssh', 'import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        recovered = run(['bash', '-c', result.stdout.splitlines()[0]], env=self.env)
        remote = json.loads(recovered.stdout)[-1]
        self.assertEqual(shlex.split(remote)[3], "/workspace/a'b")
        self.assertEqual(shlex.split(remote)[-1], 'echo "literal $HOME"')

    def relay(self, **updates):
        password = self.base / 'password'; password.write_text('fixture'); password.chmod(0o600)
        data = {'host': 'relay.example.com', 'port': 873, 'module': 'files', 'user': 'demo', 'base_path': 'shared', 'password_file': str(password)}
        data.update(updates); cfg = self.base / 'config.json'; cfg.write_text(json.dumps(data))
        fake(self.bin / 'rsync', 'import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        return cfg

    def test_relay_preserves_directory_slash_and_dry_run(self):
        cfg = self.relay(); directory = self.base / 'source'; directory.mkdir()
        result = run(['bash', script('rsync-relay-transfer','invoke-rsync-relay.sh'), 'upload', '--config', cfg, '--local-path', str(directory) + '/'], env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout)
        self.assertIn('--dry-run', args); self.assertEqual(args[-2], str(directory) + '/')

    def test_relay_rejects_config_traversal(self):
        cfg = self.relay(base_path='../elsewhere')
        result = run(['bash', script('rsync-relay-transfer','invoke-rsync-relay.sh'), 'list', '--config', cfg], env=self.env)
        self.assertNotEqual(result.returncode, 0)

    def test_relay_rejects_readable_password_file(self):
        cfg = self.relay(); (self.base / 'password').chmod(0o644)
        result = run(['bash', script('rsync-relay-transfer','invoke-rsync-relay.sh'), 'list', '--config', cfg], env=self.env)
        self.assertNotEqual(result.returncode, 0)

    def test_stop_all_propagates_ssh_failure(self):
        fake(self.bin / 'ssh', 'import sys\nsys.exit(255)\n')
        hosts = self.base / 'hosts'; hosts.write_text('worker.example.com slots=8\n')
        result = run(['bash', script('k8s-multi-node-deploy','stop_all.sh'), hosts], env=self.env)
        self.assertNotEqual(result.returncode, 0)

    def bench(self, failure=False, netcheck=False):
        fake(self.bin / 'timeout', 'import sys\nprint("1024 1 float sum -1 1 200 200 0 1 200 200 0")\nsys.exit(' + ('7' if failure else '0') + ')\n')
        hosts = self.base / 'hosts'; hosts.write_text('worker1 slots=8\nworker2 slots=8\n')
        return run(['bash', script('k8s-multi-node-deploy','mccl_bench.sh'), hosts, *(['--netcheck'] if netcheck else [])], cwd=self.base, env=self.env)

    def test_benchmark_propagates_process_exit(self):
        self.assertNotEqual(self.bench(failure=True).returncode, 0)

    def test_benchmark_success(self):
        result = self.bench(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_netcheck_success(self):
        result = self.bench(netcheck=True); self.assertEqual(result.returncode, 0, result.stderr)

    def test_cluster_lock_cannot_overwrite_owner(self):
        text = script('k8s-multi-node-deploy','auto_fault_manager.sh').read_text()
        names = ['acquire_cluster_lock','write_cluster_lock_owner','heartbeat_cluster_lock']
        functions = '\n'.join(re.search(r'(?ms)^' + name + r'\(\) \{\n.*?^\}', text)[0] for name in names)
        lock = self.base / 'lock'; lock.mkdir(); (lock/'owner').write_text('existing-owner\n')
        # Simulate a live owner. Exit when the contender enters standby.
        source = functions + '\nlog() { :; }\nis_cluster_lock_stale() { return 1; }\nsleep() { exit 77; }\n'
        source += 'CLUSTER_LOCK_PATH=$1\nCLUSTER_LOCK_OWNER_FILE=$1/owner\nCLUSTER_LOCK_HEARTBEAT_FILE=$1/heartbeat\nCLUSTER_LOCK_WAIT_SEC=1\nacquire_cluster_lock\n'
        result = run(['bash', '-c', source, 'fixture', lock], env=self.env)
        self.assertEqual((lock/'owner').read_text(), 'existing-owner\n')
        self.assertEqual(result.returncode, 77)

    def test_pid_cleanup_only_own_file(self):
        text = script('k8s-multi-node-deploy','auto_fault_manager.sh').read_text()
        function = re.search(r'(?ms)^cleanup_pid_file\(\) \{\n.*?^\}',text)[0]
        pid = self.base/'manager.pid'; pid.write_text('99999999\n')
        run(['bash','-c',function+'\nPID_FILE=$1\ncleanup_pid_file\n','fixture',pid])
        self.assertTrue(pid.exists())



class Hostfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load('k8s-multi-node-deploy', 'hostfile_from_pods.py')

    def snapshots(self):
        dep = {'metadata': {'namespace': 'demo', 'uid': 'dep'}, 'spec': {'selector': {'matchLabels': {'workload': 'demo'}, 'matchExpressions': [{'key': 'enabled', 'operator': 'Exists'}]}}}
        rs = {'items': [{'metadata': {'namespace': 'demo', 'uid': 'rs', 'ownerReferences': [{'uid': 'dep', 'controller': True}]}}]}
        pod = {'metadata': {'namespace': 'demo', 'labels': {'workload': 'demo', 'enabled': 'yes'}, 'ownerReferences': [{'uid': 'rs', 'controller': True}]},
               'spec': {'nodeName': 'node1', 'hostNetwork': True, 'containers': [{'name': 'app', 'resources': {'limits': {'mthreads.com/gpu': '8'}}}]},
               'status': {'phase': 'Running', 'hostIP': '192.0.2.1', 'conditions': [{'type': 'Ready', 'status': 'True'}], 'containerStatuses': [{'name': 'app', 'ready': True}]}}
        return dep, rs, {'items': [pod]}

    def test_owned_ready_pod(self):
        self.assertEqual(self.mod.render(*self.snapshots(), 'app', 1, 8), '192.0.2.1 slots=8\n')

    def test_foreign_owner_rejected(self):
        dep, rs, pods = self.snapshots(); pods['items'][0]['metadata']['ownerReferences'][0]['uid'] = 'foreign'
        with self.assertRaises(ValueError): self.mod.render(dep, rs, pods, 'app', 1, 8)

    def test_running_but_not_ready_rejected(self):
        dep, rs, pods = self.snapshots(); pods['items'][0]['status']['conditions'][0]['status'] = 'False'
        with self.assertRaises(ValueError): self.mod.render(dep, rs, pods, 'app', 1, 8)

    def test_selector_expression_required(self):
        dep, rs, pods = self.snapshots(); del pods['items'][0]['metadata']['labels']['enabled']
        with self.assertRaises(ValueError): self.mod.render(dep, rs, pods, 'app', 1, 8)

    def test_duplicate_node_rejected(self):
        dep, rs, pods = self.snapshots(); pods['items'].append(copy.deepcopy(pods['items'][0]))
        with self.assertRaises(ValueError): self.mod.render(dep, rs, pods, 'app', 1, 8)

    def test_slots_cannot_exceed_allocation(self):
        with self.assertRaises(ValueError): self.mod.render(*self.snapshots(), 'app', 1, 16)

    def test_notin_matches_missing_label(self):
        self.assertTrue(self.mod.matches({}, {'matchExpressions': [{'key': 'excluded', 'operator': 'NotIn', 'values': ['yes']}]}))


class OperationalEdges(unittest.TestCase):
    setUp = Shell.setUp
    def test_setup_password_mode_and_overwrite_guard(self):
        cfg = self.base / 'relay'
        args = ['bash', script('rsync-relay-transfer','setup-relay-config.sh'), '--host', 'relay.example.com', '--port', '873', '--user', 'demo', '--module', 'files', '--config-dir', cfg]
        result = run(args, input='fixture-pass\n', env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((cfg/'password.txt').stat().st_mode & 0o777, 0o600)
        second = run(args, input='replacement\n', env=self.env)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((cfg/'password.txt').read_text(), 'fixture-pass\n')

    def test_netcheck_phase2_failure_is_nonzero(self):
        fake(self.bin/'timeout', 'import sys,pathlib\nh=pathlib.Path(sys.argv[sys.argv.index("-hostfile")+1]).read_text()\nprint("1024 1 float sum -1 1 200 200 0 1 200 200 0")\nsys.exit(7 if "worker4 " in h else 0)\n')
        hosts=self.base/'hosts'; hosts.write_text('worker1 slots=8\nworker2 slots=8\nworker3 slots=8\nworker4 slots=8\n')
        result=run(['bash',script('k8s-multi-node-deploy','mccl_bench.sh'),hosts,'--netcheck'],cwd=self.base,env=self.env)
        self.assertIn('Phase 2 FAIL', result.stdout)
        self.assertNotEqual(result.returncode,0)

    def test_stop_preview_never_executes_kill(self):
        # Execute the remote script locally in a sandbox with fake GPU and kill commands.
        fake(self.bin/'ssh', 'import subprocess,sys\nbody="kill() { echo UNEXPECTED_KILL; exit 99; };\\n"+sys.stdin.read()\nsys.exit(subprocess.run(["bash","-s","--",sys.argv[-1]],input=body,text=True).returncode)\n')
        fake(self.bin/'mthreads-gmi', 'print("Processes:\n0 424242 python 1000MiB")\n'.replace('Processes:\n', 'Processes:\\n'))
        hosts=self.base/'hosts'; hosts.write_text('worker1 slots=8\n')
        result=run(['bash',script('k8s-multi-node-deploy','stop_all.sh'),hosts],env=self.env)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('would_kill: 424242',result.stdout)


if __name__ == '__main__':
    unittest.main()
