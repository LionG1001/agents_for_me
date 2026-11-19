"""Portable installer and native Windows regressions, without network access."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import base64

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / 'repo'
        self.source = self.repo / 'skills/demo'
        self.source.mkdir(parents=True)
        (self.source / 'SKILL.md').write_text('---\nname: demo\ndescription: fixture\n---\n', encoding='utf-8')
        self.dest = base / 'codex/skills'
        self.mod = load(ROOT / 'scripts/install_skills.py')
        self.scope = patch.object(self.mod, 'ROOT', self.repo)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def test_preview_makes_no_directories(self):
        self.mod.install(self.dest, dry_run=True)
        self.assertFalse(self.dest.exists())

    def test_updates_keep_rollback_and_destination_only_files(self):
        self.mod.install(self.dest)
        entry = self.dest / 'demo/SKILL.md'
        old = entry.read_bytes()
        (self.dest / 'demo/local.md').write_text('local')
        (self.source / 'SKILL.md').write_text('changed')
        with self.assertRaises(ValueError):
            self.mod.install(self.dest)
        self.assertEqual(entry.read_bytes(), old)
        self.mod.install(self.dest, update=True)
        self.assertEqual(entry.read_text(), 'changed')
        self.assertEqual((self.dest / 'demo/local.md').read_text(), 'local')
        backup = list((self.dest.parent / 'backups').glob('*/demo/SKILL.md'))
        self.assertEqual(len(backup), 1)
        self.assertEqual(backup[0].read_bytes(), old)
        self.mod.install(self.dest, update=True)
        self.assertEqual(len(list((self.dest.parent / 'backups').iterdir())), 1)

    def test_failed_publish_restores_original_and_releases_lock(self):
        self.mod.install(self.dest)
        old = (self.dest / 'demo/SKILL.md').read_bytes()
        (self.source / 'SKILL.md').write_text('changed')
        rename = Path.rename
        def fail_stage(path, target):
            if path.name.startswith('.agents-for-me-stage-'):
                raise OSError('fixture publication failure')
            return rename(path, target)
        with patch.object(Path, 'rename', fail_stage), self.assertRaises(OSError):
            self.mod.install(self.dest, update=True)
        self.assertEqual((self.dest / 'demo/SKILL.md').read_bytes(), old)
        self.assertFalse((self.dest / '.agents-for-me-install.lock').exists())

    def test_credentials_fail_before_first_write(self):
        (self.source / '.env').write_text('fixture')
        with self.assertRaises(ValueError):
            self.mod.install(self.dest)
        self.assertFalse(self.dest.exists())


class ClusterPlatforms(unittest.TestCase):
    def setUp(self):
        self.mod = load(ROOT / 'skills/multi-cluster-access/scripts/clusterctl.py')

    def test_windows_public_key_proxy_preserves_spaces(self):
        with tempfile.TemporaryDirectory(prefix='cluster key ') as td:
            key = Path(td) / 'id'; key.write_text('fixture')
            endpoint = {'host': 'worker.example.com', 'username': 'dev', 'auth_mode': 'publickey', 'key_path': str(key)}
            cluster = {'bastions': {'gate': endpoint}, 'known_hosts_file': str(Path(td) / 'known hosts')}
            with patch.object(self.mod, 'WINDOWS', True):
                argv = self.mod.ssh_base(cluster, {**endpoint, 'bastion': 'gate'})
                with self.mod.ssh_environment(cluster, {**endpoint, 'bastion': 'gate'}) as env:
                    self.assertNotIn('MCA_TARGET_PASSWORD_FILE', env)
            proxy = next(x for x in argv if x.startswith('ProxyCommand='))
            self.assertIn('"' + str(key) + '"', proxy)
            self.assertIn('StrictHostKeyChecking=yes', proxy)

    def test_windows_password_refuses_before_reading_secret(self):
        endpoint = {'auth_mode': 'password'}
        with patch.object(self.mod, 'WINDOWS', True), patch.object(self.mod, 'get_secret', side_effect=AssertionError('must not read')):
            with self.assertRaises(RuntimeError):
                self.mod.ssh_base({'bastions': {'gate': endpoint}}, {**endpoint, 'bastion': 'gate'})

    def test_windows_vpn_mutation_refuses_without_commands(self):
        with patch.object(self.mod.sys, 'platform', 'win32'), patch.object(self.mod, 'run', side_effect=AssertionError('must not run')):
            with self.assertRaises(RuntimeError):
                self.mod.start_vpn('demo', {'vpn': {'probe_host': 'example.com'}})


@unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell/NTFS ACLs')
class NativePowerShell(unittest.TestCase):
    def ps(self, source):
        encoded = base64.b64encode(source.encode('utf-16le')).decode('ascii')
        env = os.environ.copy()
        # PowerShell 7's inherited module path can load incompatible Core modules in 5.1.
        env['PSModulePath'] = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/Modules')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand',
                                 encoded], text=True, encoding='utf-8', capture_output=True, timeout=30, env=env)
        return result

    def test_all_scripts_parse_in_windows_powershell_51(self):
        result = self.ps("$ErrorActionPreference='Stop'; $errorsFound=@(); Get-ChildItem -LiteralPath '" + str(ROOT) + "' -Recurse -Filter '*.ps1' | ForEach-Object { $tokens=$null; $parseErrors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$parseErrors); $errorsFound += $parseErrors }; if ($errorsFound.Count) { $errorsFound | ForEach-Object { Write-Output $_.Message }; exit 1 }")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_container_dry_run_preserves_remote_quoting(self):
        path = ROOT / 'skills/remote-container-workspace/scripts/connect-container.ps1'
        result = self.ps("& '" + str(path) + "' -HostName worker.example.com -UserName dev -Container app -WorkDir '/workspace/a''b' -Command 'echo \"literal $HOME\"' -DryRun | ConvertTo-Json -Depth 5")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(result.stdout)['Arguments']
        self.assertEqual(shlex.split(argv[-1])[3], "/workspace/a'b")
        self.assertEqual(shlex.split(argv[-1])[-1], 'echo "literal $HOME"')

    def test_relay_setup_private_acl_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td) / 'relay'
            path = ROOT / 'skills/rsync-relay-transfer/scripts/setup-relay-config.ps1'
            command = "& '" + str(path) + "' -RelayHost relay.example.com -Port 873 -Module files -User demo -ConfigDirectory '" + str(directory) + "' -Password (ConvertTo-SecureString fixture -AsPlainText -Force)"
            result = self.ps(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            check = self.ps("$acl=Get-Acl -LiteralPath '" + str(directory / 'password.txt') + "'; if (-not $acl.AreAccessRulesProtected -or @($acl.Access).Count -ne 1) { exit 1 }")
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertNotEqual(self.ps(command).returncode, 0)
            self.assertEqual((directory / 'password.txt').read_text(encoding='utf-8').strip(), 'fixture')


if __name__ == '__main__':
    unittest.main()
