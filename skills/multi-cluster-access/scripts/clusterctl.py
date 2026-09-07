#!/usr/bin/env python3
"""Manage registered VPN, bastion, SSH target, and container task access."""

from __future__ import annotations

import argparse
import copy
import fcntl
import getpass
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SERVICE = "codex.multi-cluster-access"
DEFAULT_CONFIG = Path.home() / ".config" / "codex" / "multi-cluster-access" / "clusters.json"
ASKPASS = Path(__file__).with_name("askpass.py")


def run(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=capture, env=env)


def load_config() -> dict[str, Any]:
    path = Path(os.environ.get("CLUSTER_ACCESS_CONFIG", DEFAULT_CONFIG)).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 2 or not isinstance(data.get("clusters"), dict):
        raise ValueError(f"不支持的注册表格式：{path}")
    validate_config(data)
    return data


def validate_config(data: dict[str, Any]) -> None:
    for cluster_name, cluster in data["clusters"].items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", cluster_name):
            raise ValueError(f"无效集群名：{cluster_name!r}")
        bastions = cluster.get("bastions", {})
        targets = cluster.get("targets", {})
        if not bastions or not targets:
            raise ValueError(f"{cluster_name}: 必须显式登记堡垒机和目标资产")
        for kind, entries in (("bastion", bastions), ("target", targets)):
            for name, item in entries.items():
                port = int(item.get("port", 22))
                if not 1 <= port <= 65535 or not item.get("host") or not item.get("username"):
                    raise ValueError(f"{cluster_name}/{kind}/{name}: endpoint 无效")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", str(item["host"])) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", str(item["username"])):
                    raise ValueError(f"{cluster_name}/{kind}/{name}: host/username 无效")
                mode = item.get("auth_mode")
                if mode == "password" and not item.get("secret_ref"):
                    raise ValueError(f"{cluster_name}/{kind}/{name}: password 缺少 secret_ref")
                if mode == "publickey" and not Path(str(item.get("key_path", ""))).expanduser().is_absolute():
                    raise ValueError(f"{cluster_name}/{kind}/{name}: publickey 缺少绝对 key_path")
                if mode not in {"password", "publickey"}:
                    raise ValueError(f"{cluster_name}/{kind}/{name}: 必须显式设置 auth_mode")
                if kind == "target" and item.get("bastion") not in bastions:
                    raise ValueError(f"{cluster_name}/target/{name}: 未知堡垒机")
        vpn = cluster.get("vpn")
        if vpn and (vpn.get("auth_mode") != "password" or not vpn.get("secret_ref")):
            raise ValueError(f"{cluster_name}: VPN 当前只支持显式 password auth_mode")
    used_profiles: dict[tuple[str, str], str] = {}
    for task_name, task in data.get("tasks", {}).items():
        cluster_name = task.get("cluster")
        if cluster_name not in data["clusters"]:
            raise ValueError(f"任务 {task_name}: 未知集群")
        cluster = data["clusters"][cluster_name]
        if task.get("target") not in cluster.get("targets", {}):
            raise ValueError(f"任务 {task_name}: 未知目标")
        profile = task.get("access_profile")
        if not profile or profile == "default" or profile not in cluster.get("access_profiles", {}):
            raise ValueError(f"任务 {task_name}: 必须绑定独立的 access_profile")
        profile_key = (cluster_name, profile)
        if profile_key in used_profiles:
            raise ValueError(f"任务 {task_name}: access_profile 已被 {used_profiles[profile_key]} 使用")
        used_profiles[profile_key] = task_name
        if task.get("workdir") and not Path(str(task["workdir"])).is_absolute():
            raise ValueError(f"任务 {task_name}: workdir 必须是绝对路径")


def get_secret(ref: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@/-]+", ref):
        raise ValueError(f"无效 secret_ref：{ref!r}")
    secret_command = os.environ.get("CLUSTER_ACCESS_SECRET_COMMAND")
    if secret_command:
        completed = run(
            [*shlex.split(secret_command), ref],
            check=False,
            capture=True,
        )
        value = completed.stdout.rstrip("\r\n")
        if completed.returncode != 0 or not value:
            raise RuntimeError(f"集中凭据服务无法解析 secret_ref：{ref}")
        return value
    import keyring  # Optional unless the desktop credential backend is selected.
    value = keyring.get_password(SERVICE, ref)
    if value is None:
        raise RuntimeError(f"密钥环缺少 secret_ref：{ref}；请运行 set-secret")
    return value


def resolve(
    config: dict[str, Any], name: str
) -> tuple[str, str | None, dict[str, Any] | None]:
    tasks = config.get("tasks", {})
    if name in tasks:
        task = tasks[name]
        return task["cluster"], task["target"], task
    if name in config["clusters"]:
        return name, None, None
    matches: list[tuple[str, str]] = []
    for cluster_name, cluster in config["clusters"].items():
        if name in cluster.get("targets", {}):
            matches.append((cluster_name, name))
    if len(matches) == 1:
        return matches[0][0], matches[0][1], None
    if len(matches) > 1:
        raise ValueError(f"目标名 {name!r} 在多个集群中存在，请使用任务名")
    raise KeyError(f"未登记集群、目标或任务：{name}")


def unit_name(cluster_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", cluster_name)
    return f"multi-cluster-vpn-{safe}.service"


def route_uses_vpn(host: str) -> bool:
    result = run(["ip", "route", "get", host], check=False, capture=True)
    return result.returncode == 0 and re.search(r" dev (tun|tap)[^ ]* ", result.stdout) is not None


def tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def vpn_ready(vpn: dict[str, Any]) -> bool:
    return route_uses_vpn(vpn["probe_host"]) and tcp_reachable(
        vpn["probe_host"], int(vpn["probe_port"])
    )


def default_route_snapshot() -> str:
    return run(["ip", "route", "show", "default"], check=False, capture=True).stdout.strip()


def dns_snapshot(name: str) -> tuple[str, ...]:
    try:
        return tuple(sorted({item[4][0] for item in socket.getaddrinfo(name, None)}))
    except socket.gaierror:
        return ()


@contextmanager
def mutation_lock(cluster_name: str):
    runtime_dir = Path(f"/run/user/{os.getuid()}")
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = runtime_dir / f"mca-{cluster_name}.lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def redact_log(value: str) -> str:
    for pattern in (
        r"(?i)(?:password|passwd|token|authorization|secret)\s*[:=]\s*\S+",
        r"(?i)auth-user-pass\s+\S+",
    ):
        value = re.sub(pattern, "[REDACTED]", value)
    return value


def _start_vpn_locked(cluster_name: str, cluster: dict[str, Any]) -> None:
    vpn = cluster.get("vpn")
    if not vpn:
        return
    if vpn_ready(vpn):
        print(f"{cluster_name}: VPN ready")
        return
    server_name = vpn.get("server_name")
    if not server_name:
        raise ValueError(f"{cluster_name}: 缺少 vpn.server_name，拒绝无身份校验连接")
    profile = Path(vpn["profile"]).expanduser()
    if not profile.is_absolute() or not profile.is_file():
        raise FileNotFoundError(profile)
    before_default = default_route_snapshot()
    dns_name = str(vpn.get("dns_probe_name") or server_name)
    before_dns = dns_snapshot(dns_name)
    if not before_dns:
        raise RuntimeError(f"{cluster_name}: VPN 前 DNS 探测失败：{dns_name}")
    password = get_secret(vpn["secret_ref"])
    runtime_dir = Path(f"/run/user/{os.getuid()}")
    fd, auth_name = tempfile.mkstemp(
        prefix=f"mca-{cluster_name}-", dir=runtime_dir, text=True
    )
    auth_path = Path(auth_name)
    started = False
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(vpn["username"] + "\n" + password + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        del password
        unit = unit_name(cluster_name)
        run(["sudo", "systemctl", "stop", unit], check=False, capture=True)
        run(["sudo", "systemctl", "reset-failed", unit], check=False, capture=True)
        run(
            [
                "sudo",
                "systemd-run",
                f"--unit={unit.removesuffix('.service')}",
                "--collect",
                "--quiet",
                "--property=Type=simple",
                "/usr/sbin/openvpn",
                "--config",
                str(profile),
                "--auth-user-pass",
                str(auth_path),
                "--auth-nocache",
                "--verify-x509-name",
                server_name,
                "name",
                "--verb",
                "3",
            ]
        )
        started = True
        for _ in range(30):
            if vpn_ready(vpn):
                after_default = default_route_snapshot()
                after_dns = dns_snapshot(dns_name)
                if before_default != after_default:
                    run(["sudo", "systemctl", "stop", unit], check=False, capture=True)
                    raise RuntimeError(f"{cluster_name}: VPN 改写了默认路由，已回滚")
                if not after_dns:
                    run(["sudo", "systemctl", "stop", unit], check=False, capture=True)
                    raise RuntimeError(f"{cluster_name}: VPN 破坏了 DNS 解析，已回滚")
                print(f"{cluster_name}: VPN connected")
                return
            active = run(
                ["sudo", "systemctl", "is-active", "--quiet", unit], check=False
            )
            if active.returncode != 0:
                break
            time.sleep(1)
        journal = run(
            ["sudo", "journalctl", "-u", unit, "-n", "20", "--no-pager"],
            check=False,
            capture=True,
        )
        print(redact_log(journal.stdout + journal.stderr), file=sys.stderr)
        raise RuntimeError(f"{cluster_name}: VPN 启动失败")
    except BaseException:
        if started:
            run(["sudo", "systemctl", "stop", unit_name(cluster_name)], check=False, capture=True)
        raise
    finally:
        auth_path.unlink(missing_ok=True)


def start_vpn(cluster_name: str, cluster: dict[str, Any]) -> None:
    vpn = cluster.get("vpn")
    if not vpn or vpn_ready(vpn):
        if vpn:
            print(f"{cluster_name}: VPN ready")
        return
    with mutation_lock(cluster_name):
        _start_vpn_locked(cluster_name, cluster)


def stop_vpn(cluster_name: str) -> None:
    with mutation_lock(cluster_name):
        run(
            ["sudo", "systemctl", "stop", unit_name(cluster_name)],
            check=True,
            capture=True,
        )
    print(f"{cluster_name}: VPN stopped")


def endpoint(
    config: dict[str, Any], name: str
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    cluster_name, target_name, task = resolve(config, name)
    if not target_name:
        raise ValueError("该操作需要目标机器或任务名，不能只指定集群")
    cluster = copy.deepcopy(config["clusters"][cluster_name])
    target = copy.deepcopy(cluster["targets"][target_name])
    profile_name = (task or {}).get("access_profile")
    if profile_name and profile_name != "default":
        profiles = cluster.get("access_profiles", {})
        if profile_name not in profiles:
            raise ValueError(f"任务 {name!r} 引用了未登记 access_profile：{profile_name}")
        profile = profiles[profile_name]
        bastion_name = target["bastion"]
        bastion_override = profile.get("bastions", {}).get(bastion_name, {})
        target_override = profile.get("targets", {}).get(
            target_name, profile.get("target_default", {})
        )
        allowed = {"username", "auth_mode", "secret_ref", "key_path"}
        cluster["bastions"][bastion_name].update(
            {key: value for key, value in bastion_override.items() if key in allowed}
        )
        target.update(
            {key: value for key, value in target_override.items() if key in allowed}
        )
    cluster["targets"][target_name] = target
    validate_config({"clusters": {cluster_name: cluster}, "tasks": {}})
    return cluster_name, cluster, target, task


def auth_options(endpoint_config: dict[str, Any]) -> list[str]:
    mode = endpoint_config["auth_mode"]
    common = ["-o", "IdentitiesOnly=yes", "-o", "NumberOfPasswordPrompts=1"]
    if mode == "password":
        return [
            *common,
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "PubkeyAuthentication=no",
        ]
    if mode == "publickey":
        key_path = Path(endpoint_config["key_path"]).expanduser()
        if not key_path.is_file():
            raise FileNotFoundError(key_path)
        return [
            *common,
            "-o",
            "BatchMode=yes",
            "-o",
            "PreferredAuthentications=publickey",
            "-i",
            str(key_path),
        ]
    raise ValueError(f"不支持的 auth_mode：{mode}")


def ssh_base(cluster: dict[str, Any], target: dict[str, Any]) -> list[str]:
    bastion = cluster["bastions"][target["bastion"]]
    known_hosts = str(
        Path(cluster.get("known_hosts_file", Path.home() / ".ssh" / "known_hosts")).expanduser()
    )
    host_key_options = [
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
    ]
    proxy_parts = [
        "ssh",
        *host_key_options,
        "-o",
        "ConnectTimeout=12",
        *auth_options(bastion),
        "-p",
        str(int(bastion.get("port", 22))),
        "-W",
        "%h:%p",
        bastion["username"] + "@" + bastion["host"],
    ]
    proxy = shlex.join(proxy_parts)
    args = [
        "ssh",
        *host_key_options,
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        *auth_options(target),
        "-o",
        f"ProxyCommand={proxy}",
        "-p",
        str(int(target.get("port", 22))),
        f"{target['username']}@{target['host']}",
    ]
    return args


def write_secret_file(runtime_dir: Path, prefix: str, secret_ref: str) -> Path:
    value = get_secret(secret_ref)
    fd, name = tempfile.mkstemp(prefix=prefix, dir=runtime_dir, text=True)
    path = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        del value
    return path


@contextmanager
def ssh_environment(cluster: dict[str, Any], target: dict[str, Any]):
    bastion = cluster["bastions"][target["bastion"]]
    runtime_dir = Path(f"/run/user/{os.getuid()}")
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths: list[Path] = []
    env = os.environ.copy()
    env.update(
        {
            "SSH_ASKPASS": str(ASKPASS),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": env.get("DISPLAY", ":0"),
            "MCA_BASTION_MATCH": (bastion["username"] + "@" + bastion["host"]).lower(),
            "MCA_TARGET_MATCH": (target["username"] + "@" + target["host"]).lower(),
        }
    )
    try:
        if bastion["auth_mode"] == "password":
            path = write_secret_file(runtime_dir, "mca-bastion-", bastion["secret_ref"])
            paths.append(path)
            env["MCA_BASTION_PASSWORD_FILE"] = str(path)
        if target["auth_mode"] == "password":
            path = write_secret_file(runtime_dir, "mca-target-", target["secret_ref"])
            paths.append(path)
            env["MCA_TARGET_PASSWORD_FILE"] = str(path)
        yield env
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        for key in ("MCA_BASTION_PASSWORD_FILE", "MCA_TARGET_PASSWORD_FILE"):
            env.pop(key, None)


def run_ssh(
    config: dict[str, Any],
    name: str,
    remote_args: list[str],
    interactive: bool,
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    cluster_name, cluster, target, _ = endpoint(config, name)
    vpn = cluster.get("vpn")
    if vpn and not vpn_ready(vpn):
        raise RuntimeError(
            f"{cluster_name}: VPN 未就绪；请先显式运行 clusterctl start {cluster_name}"
        )
    args = ssh_base(cluster, target)
    if interactive:
        args.insert(1, "-tt")
    if remote_args:
        args.append(shlex.join(remote_args))
    with ssh_environment(cluster, target) as env:
        # Deliberately inherit the caller's process group. The MCP parent starts
        # clusterctl in its own group and can therefore terminate SSH/ProxyCommand
        # descendants together when a tool timeout expires.
        return subprocess.run(args, env=env, text=True, capture_output=capture)


def print_resolved(config: dict[str, Any], name: str) -> None:
    cluster_name, target_name, task = resolve(config, name)
    result: dict[str, Any] = {"cluster": cluster_name}
    if target_name:
        _, _, target, _ = endpoint(config, name)
        result.update(
            {
                "target": target_name,
                "host": target["host"],
                "username": target["username"],
                "bastion": target["bastion"],
                "access_profile": (task or {}).get("access_profile", "default"),
            }
        )
    if task:
        result["container"] = task.get("container")
        result["workdir"] = task.get("workdir")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def inspect_container(config: dict[str, Any], task_name: str, task: dict[str, Any]) -> dict[str, Any]:
    container = task["container"]
    inspect = run_ssh(
        config,
        task_name,
        [
            "docker",
            "inspect",
            "--format",
            '{"name":{{json .Name}},"image":{{json .Config.Image}},"image_id":{{json .Image}},"running":{{json .State.Running}}}',
            container,
        ],
        False,
        capture=True,
    )
    if inspect.returncode != 0:
        raise RuntimeError(f"容器检查失败：{redact_log(inspect.stderr).strip()}")
    try:
        metadata = json.loads(inspect.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("容器检查返回了无法解析的结果") from exc
    if not metadata.get("running"):
        raise RuntimeError(f"容器 {container} 未运行；MCP 不会代为启动")
    expected_image = task.get("expected_image")
    if expected_image and metadata.get("image") != expected_image:
        raise RuntimeError(
            f"容器镜像不匹配：expected={expected_image!r}, actual={metadata.get('image')!r}"
        )
    expected_image_id = task.get("expected_image_id")
    if expected_image_id and metadata.get("image_id") != expected_image_id:
        raise RuntimeError(
            f"容器镜像 ID 不匹配：expected={expected_image_id!r}, actual={metadata.get('image_id')!r}"
        )
    workdir = run_ssh(
        config,
        task_name,
        ["docker", "exec", "-w", task["workdir"], container, "test", "-d", task["workdir"]],
        False,
        capture=True,
    )
    if workdir.returncode != 0:
        raise RuntimeError(f"容器工作目录不存在或不可访问：{task['workdir']}")
    expected_mounts = [str(item) for item in task.get("expected_mounts", [])]
    if expected_mounts:
        mounts = run_ssh(
            config,
            task_name,
            ["docker", "inspect", "--format", "{{range .Mounts}}{{println .Destination}}{{end}}", container],
            False,
            capture=True,
        )
        if mounts.returncode != 0:
            raise RuntimeError("容器挂载检查失败")
        actual_mounts = set(mounts.stdout.splitlines())
        missing = sorted(set(expected_mounts) - actual_mounts)
        if missing:
            raise RuntimeError(f"容器缺少预期挂载：{', '.join(missing)}")
    metadata.update(
        {
            "container": container,
            "workdir": task["workdir"],
            "workdir_exists": True,
            "expected_image": expected_image,
            "expected_image_id": expected_image_id,
            "expected_mounts": expected_mounts,
        }
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="clusterctl")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    for command in (
        "resolve",
        "status",
        "start",
        "stop",
        "ssh",
        "container-shell",
        "container-info",
    ):
        item = sub.add_parser(command)
        item.add_argument("name")
    for command in ("exec", "container-exec"):
        item = sub.add_parser(command)
        item.add_argument("name")
        item.add_argument("remote_command", nargs=argparse.REMAINDER)
    secret = sub.add_parser("set-secret")
    secret.add_argument("secret_ref")
    return root


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()
    if args.command == "list":
        print("clusters:", ", ".join(sorted(config["clusters"])))
        targets = [
            f"{cluster_name}/{target_name}"
            for cluster_name, cluster in config["clusters"].items()
            for target_name in cluster.get("targets", {})
        ]
        print("targets:", ", ".join(sorted(targets)))
        print("tasks:", ", ".join(sorted(config.get("tasks", {}))))
        return 0
    if args.command == "set-secret":
        first = getpass.getpass(f"Secret for {args.secret_ref}: ")
        second = getpass.getpass("Confirm: ")
        if not first or first != second:
            raise ValueError("secret 为空或两次输入不一致")
        import keyring
        keyring.set_password(SERVICE, args.secret_ref, first)
        print(f"stored: {args.secret_ref}")
        return 0

    cluster_name, _, task = resolve(config, args.name)
    cluster = config["clusters"][cluster_name]
    if args.command == "resolve":
        print_resolved(config, args.name)
    elif args.command == "status":
        vpn = cluster.get("vpn")
        ready = not vpn or vpn_ready(vpn)
        active = run(
            ["sudo", "systemctl", "is-active", unit_name(cluster_name)],
            check=False,
            capture=True,
        ).stdout.strip()
        print(
            f"cluster={cluster_name} service={active or 'inactive'} "
            f"ready={str(ready).lower()}"
        )
        return 0 if ready else 1
    elif args.command == "start":
        start_vpn(cluster_name, cluster)
    elif args.command == "stop":
        stop_vpn(cluster_name)
    elif args.command == "ssh":
        return run_ssh(config, args.name, [], True).returncode
    elif args.command == "exec":
        command = (
            args.remote_command[1:]
            if args.remote_command[:1] == ["--"]
            else args.remote_command
        )
        if not command:
            raise ValueError("exec 需要 -- 后的远端命令")
        return run_ssh(config, args.name, command, False).returncode
    elif args.command in ("container-shell", "container-info", "container-exec"):
        if not task or not task.get("container") or not task.get("workdir"):
            raise ValueError("容器操作必须使用包含 container 和 workdir 的任务名")
        metadata = inspect_container(config, args.name, task)
        if args.command == "container-info":
            print(json.dumps(metadata, ensure_ascii=False, indent=2))
            return 0
        if args.command == "container-shell":
            remote = [
                "docker",
                "exec",
                "-it",
                "-w",
                task["workdir"],
                task["container"],
                "bash",
            ]
            return run_ssh(config, args.name, remote, True).returncode
        command = (
            args.remote_command[1:]
            if args.remote_command[:1] == ["--"]
            else args.remote_command
        )
        if not command:
            raise ValueError("container-exec 需要 -- 后的容器命令")
        remote = [
            "docker",
            "exec",
            "-w",
            task["workdir"],
            task["container"],
            *command,
        ]
        return run_ssh(config, args.name, remote, False).returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
