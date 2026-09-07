# 集群注册表格式

默认位置：`~/.config/codex/multi-cluster-access/clusters.json`。可用环境变量 `CLUSTER_ACCESS_CONFIG` 覆盖。

```json
{
  "version": 2,
  "clusters": {
    "cluster-name": {
      "vpn": {
        "profile": "/absolute/path/client.ovpn",
        "auth_mode": "password",
        "username": "vpn-user",
        "secret_ref": "cluster-name/vpn/vpn-user",
        "server_name": "vpn.example.com",
        "probe_host": "10.0.0.10",
        "probe_port": 22022
      },
      "bastions": {
        "default": {
          "host": "10.0.0.10",
          "port": 22022,
          "username": "bastion-user",
          "auth_mode": "password",
          "secret_ref": "cluster-name/bastion/bastion-user"
        }
      },
      "targets": {
        "worker01": {
          "host": "10.0.1.1",
          "port": 22,
          "username": "worker-user",
          "auth_mode": "password",
          "secret_ref": "cluster-name/target/worker-user",
          "bastion": "default"
        }
      },
      "access_profiles": {
        "task-account-a": {
          "bastions": {
            "default": {
              "username": "rotating-bastion-user",
              "secret_ref": "cluster-name/profiles/task-account-a/bastion"
            }
          },
          "targets": {
            "worker01": {
              "username": "rotating-worker-user",
              "secret_ref": "cluster-name/profiles/task-account-a/worker01"
            }
          }
        }
      }
    }
  },
  "tasks": {
    "project-task": {
      "cluster": "cluster-name",
      "target": "worker01",
      "access_profile": "task-account-a",
      "container": "container-name",
      "workdir": "/absolute/container/path"
    }
  }
}
```

约束：

- `profile` 和任务 `workdir` 必须是绝对路径。
- 每个独立账户使用独立 `secret_ref`；同名账户只有明确共用密码时才能复用引用。
- 每个任务必须显式绑定独立且非 `default` 的 `access_profile`，不可被其他任务复用。profile 可以覆盖 `username`、`auth_mode`、`secret_ref`、`key_path`；不允许覆盖 host、port 或 bastion。空覆盖继承已登记身份。
- `server_name` 用于 OpenVPN 证书名称校验。缺失时 `start` 拒绝运行。
- `probe_host`/`probe_port` 应指向 VPN 建立后可用于只读 TCP 探测的堡垒机端口。
- `tasks` 只保存稳定的默认映射；运行前仍要核验容器和工作目录在线状态。

默认从桌面 keyring 读取凭据。团队 MCP 部署可设置 `CLUSTER_ACCESS_SECRET_COMMAND` 为集中凭据代理命令；`clusterctl` 会把单个 `secret_ref` 作为最后一个参数传入，并从标准输出读取 secret。该命令必须只输出 secret，错误和审计信息写标准错误，且不得记录 secret。

## 运行依赖与主机密钥

当前 CLI 面向 Linux，要求 Python 3.10+、OpenSSH；VPN 操作另需 OpenVPN、systemd、iproute2 和相应 sudo 权限。桌面凭据需要 Python keyring 和可用后端；集中凭据命令和纯公钥连接无需 keyring。

端点必须显式设置 `auth_mode`：`password` 配 `secret_ref`，`publickey` 配绝对 `key_path`。使用 `StrictHostKeyChecking=yes`；首次使用前通过可信渠道核验指纹并预置堡垒机和目标机的 known_hosts，可用集群字段 `known_hosts_file` 指定文件。不要通过关闭校验解决连接失败。

容器任务可配置 `expected_image`、`expected_image_id` 和 `expected_mounts`（容器挂载路径列表）；`container-info` 会核对在线状态、工作目录和这些预期，再允许执行命令。

VPN 启动失败会停止本次启动的 unit 并清除认证文件。成功后认证文件也会清除；需要重新读取密码的重认证场景应显式重连，当前 CLI 不提供持续凭据代理。
