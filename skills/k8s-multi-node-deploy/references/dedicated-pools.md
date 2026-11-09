# 专用池与节点恢复

## 隔离与最终分配

- 核对Deployment→ReplicaSet→Pod归属、GPU申请及真实进程。特权、hostPID或宽泛设备挂载的Pod可能不申请GPU资源却仍能访问设备，不能仅凭配额断言独占，也不能凭共存认定其导致故障。
- 永久池可用节点标签、NoSchedule污点及允许负载的匹配选择/亲和、精确容忍。污点不驱逐旧Pod，也不是针对管理员直接绑定或主动添加容忍的准入防线；清理已有负载需要对应授权。
- 永久保留池不自动意味着原负载永久为0。分别记录测试期间暂停对象、最终允许负载与副本、哪些隔离规则保留；用户最新安排取代旧恢复约定。
- 仅删Pod而控制器保持副本数会自动重建。按授权选择暂停控制器、限制调度或定向删除，不反复扩大删除范围，不修改未授权副本。

## 保留安装环境

模板修改可能触发Recreate并丢失容器可写层依赖。共享源码仍在不代表新容器依赖仍在；按新UID、containerID和boot重新验收。

只需缩容并释放特定节点时，可对相同健康状态的Pod设置一次性`controller.kubernetes.io/pod-deletion-cost`偏好，再改副本数，避免为选节点重写模板。该机制尽力而为，不保证顺序；回读实际删除节点和保留的Pod/容器身份，稳定后恢复原注释。普通缩容不必强制引入。参考[Kubernetes说明](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/#pod-deletion-cost)。

修改前保存必要spec并server dry-run，只改授权字段。Node心跳频繁改变resourceVersion；纯状态变化造成前提失败时可重读，以UID及相关spec前提保护并发配置，不能取消全部保护。

## 替换节点的就绪链

依次核对节点身份/实际驱动和设备→标准设备插件→真实训练Pod本地依赖→同一PVC资产→通信→授权训练。Node/Pod Ready不替代后续层。

CSI故障区分客户端登记、存储网络和mount namespace/宿主旧自动挂载冲突。同名目录或另一个/datapool不证明同一文件系统；按实际PV、挂载和跨节点可读性核对。用户选择共享流程时，不静默切本地盘后仍作为同条件性能数据。

重启或重建后，旧PID/进程组不能用于新实例；重新核对boot、Pod UID、containerID和进程。不可达范围保持未确认。结束时分别验证测试进程退出、GPU占用及副本状态；保留环境不等于释放Kubernetes配额。
