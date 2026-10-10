# DPS 0.9 访问与操作

DPS 运行在 `L20-12` 物理机原生 K3s。release `dps`、namespace `dps`、context `dps-l20-12`。2026-10-10 上午（Asia/Shanghai）接入独立 OpenLDAP 2.6.10；10:52:29 的 DPS LDAP 身份/授权、令牌和 UI session API 验收为 28/28。UI 验证基于会话 API，未进行浏览器视觉验收。

2026-10-10（Asia/Shanghai）PRS 已通过手动 Helm 升级启用，当前 release 为 revision 5、deployed，9 个 workload Ready。17:05:41 的 PRS 验收为 35/35，覆盖部署、实际 Pod 严格数据库 TLS、S3、Controller 的 LDAP/DPS TLS 连接与登录回归。DPS 已持久化 `prs_enabled=true`、headroom `-15%` 和 scheduler `5 秒`；实际 PowerSteering 为 2.1.0，SeaweedFS 为 4.18。

| 入口 | 地址 |
|---|---|
| 浏览器 UI | `https://ui.dps.lab` |
| DPS gRPC/TLS API | `https://api.dps.lab:443` |
| 管理 IP | `10.6.131.43` |
| 公共 CA | `/raid/vince/deploy/dps-install/config/tls/ca.crt` |
| DPS 管理员（LDAP 用户） | `dps-lab` |
| 真实 LDAP 用户密码 | `/raid/vince/deploy/dps-install/config/dps-access.json`，权限 600 |
| CLI 登录凭据 | `/raid/vince/deploy/dps-install/config/dpsctl/credentials.yaml`，文件 600、目录 700 |

当前使用独立 OpenLDAP 校验用户名与密码；`dps-lab` 属于 `dcpower-users` 组，该组映射 DPS admin。错误密码、不存在账号或空密码会被拒绝。真实组外用户可以通过身份校验并取得 roles=[]/memberOf=[] 的令牌，但没有受保护 DPS 接口权限，拓扑查询返回授权失败。OIDC 关闭。

目录地址为 `ldaps://10.6.131.43:1636`，base DN 为 `dc=dps,dc=lab`。DPS 的只读绑定服务账号和目录管理账号不是 UI 登录账户，凭据只保存在 `config/ldap/credentials.json` 等受限文件。LDAP 用于 DPS UI/API；模拟 BMC 的访问方式保持硬件说明中的设置。

此前的评估认证已退出当前方案，JWT 签名身份已一次性轮换，旧 UI/CLI 会话需重新登录。

## 从其他客户端访问 UI

客户端应能连接管理 IP 的 443 端口，将以下解析加入其 DNS 或 hosts：

```text
10.6.131.43 api.dps.lab ui.dps.lab
```

远端 L20-12 已有此解析，其他电脑尚未自动配置。取得项目公开 CA，并导入浏览器/操作系统的信任证书存储，然后访问 `https://ui.dps.lab`。只分发 `ca.crt`，不分发 `ca.key`、服务私钥或 Kubernetes 管理员 kubeconfig。保留域名访问，使证书名称和路由匹配。

使用 `dps-lab` 与凭据文件中的真实 LDAP 密码登录 UI。UI HTTPS、会话登录、经 UI 代理的版本/拓扑查询及退出流程已检查通过。

## 在 L20-12 使用 dpsctl

```bash
ssh root@L20-12
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
dpsctl server-version
dpsctl verify --dps-server --database --auth --ui
dpsctl agent list
dpsctl topology list
```

环境文件设定 `api.dps.lab:443`、CA、项目 CLI 凭据路径和 `verification/logs/dpsctl.log`。切换 LDAP 后使用安全入口重新获取凭据：

```bash
./dps-install/scripts/dps-login.sh
```

该脚本读取权限 600 的账户文件，经标准输入交给 dpsctl，不将密码写入命令行或文档。LDAP 认证、权限与旧令牌撤销记录见 `verification/reports/dps-ldap-auth.json`。

## 当前拓扑与功能范围

已导入 `dps-gb300-4rack`，110 个实体包含 72 个计算节点、32 个电源架、4 个 PDU 和 2 个供电域；每 rack 有 18 个计算节点，共 288 个 GPU。UI 列表与清单可见，拓扑保持 `inactive`。

当前安装输入为 `config/topology-4rack-dps09.json`；删除旧版 Policies 字段，
72 个节点的 AgentId 设置在 `Topology.Entities` 关系对象，路由至 `gb300-lab-agent`。已通过官方 API 与当前 hash 校验更新，并回读确认全部 72 条关联；拓扑仍为 inactive。
GB300 电源架设备规格为 33,000W、效率 0.95，注册输入为 `config/gb300-power-shelf-devices.yaml`。

Agent 已通过 mTLS 连接。DPS 0.9 的 inactive 拓扑尚不向 Agent 下发设备配置，assigned_devices=0 属于此状态；拓扑连接和深层 BMC 健康检查需要激活后执行，即使检查选项跳过写入也不能绕过该前提。当前激活会应用 MaxLPS 功率策略，本次没有执行，DPS→Agent→BMC 的完整验收延后。现有 `verification/reports/dps-topology-connection.json` 与 `dps-bmc-health.json` 保存 inactive 状态下的实际返回，不能把它们当作已经通过的检查。

导入/更新脚本保持拓扑 inactive，不激活、不配置资源组策略、不执行功率控制。拓扑激活会应用有效策略或触发默认行为，不能当作只读连通检查。2026-10-09 安装后通过实际 Agent Pod 网络 namespace 的只读验证：72 个唯一 BMC 全部 HTTPS CA 校验成功，4 rack 各 18 节点，288 GPU 和 144 CPU 清单/功率遥测正常，共 1152 次 GET。通过 nsenter 使用现有网络 namespace，没有修改 Pod spec 或写 BMC。报告为 `verification/reports/dps-pod-bmc-connectivity.json`；该证据只证明 Pod 到 BMC 网络/Redfish，Core→Agent→BMC 派发仍需激活后另行验收。PRS 与 PowerSteering 2.1.0 已启用，S3 由 SeaweedFS 4.18 提供；Zapp、依赖 Zapp 的 excursion mitigation、OIDC 及 chart 内置 PostgreSQL 保持关闭；当前通过独立 PostgreSQL 17.11 和直接 BMC 路径运行 Core/Agent/UI。

## PRS 当前状态

Core 的 PRS flag 和 PowerSteering chart 同时启用，运行时 `global.prs_enabled=true`，headroom `-15%`、scheduler `5 秒` 已持久化。PowerSteering 使用独立 PostgreSQL 17.11 的三个 PRS 数据库，严格 verify-full；SeaweedFS 的 `dps-prs` bucket 和三个持久卷已准备。PRS 服务只配置集群内访问，没有新增外部 Ingress。

现有拓扑保持 inactive，没有资源组和 PRS domain，当前 API 返回空 domain 列表。部署及连接验收见 `verification/reports/prs-installation.json`（2026-10-10T17:05:41+08，35/35）。这不证明动态功率已执行；后续拓扑/资源组启用属于独立步骤。

## 状态与维护

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
kubectl --context dps-l20-12 -n dps get pods,pvc
helm --kube-context dps-l20-12 -n dps list
./dps-install/scripts/kubernetes.sh status
./dps-install/scripts/postgresql-status.sh
./dps-install/scripts/ldap-status.sh
./hardware-sim/scripts/bmc-simulator.sh status
```

当前运行快照见 `verification/reports/dps-current-state.json` 和 `dps-delivery-status.json`；早期服务/UI/Agent Pod 网络报告按 2026-10-09 历史解读。

前置维护见 [prerequisites.md](prerequisites.md)，脚本说明见 [scripts/README.md](scripts/README.md)，实际安装步骤见 [installstep.md](../installstep.md)。检查脚本、结果和日志独立位于 `verification/`。
