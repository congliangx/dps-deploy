# DPS 0.9 前置条件与维护

远程主机 `root@L20-12`，工作目录 `/raid/vince/deploy`。2026-10-09 完成原生 K3s、独立 PostgreSQL 和 DPS 手动安装；2026-10-10 上午（Asia/Shanghai）接入独立 OpenLDAP 2.6.10，目录 18/18 检查通过；10:52:29 的 DPS 身份/授权、令牌、UI session API 验收为 28/28。UI 验证基于会话 API，未进行浏览器视觉验收。

2026-10-10（Asia/Shanghai）PRS 已通过手动 Helm 升级启用，当前 release 为 revision 5、deployed，9 个 workload Ready。17:05:41 的 PRS 验收为 35/35，覆盖部署、实际 Pod 严格数据库 TLS、S3、Controller 的 LDAP/DPS TLS 连接与登录回归。DPS 已持久化 `prs_enabled=true`、headroom `-15%` 和 scheduler `5 秒`；实际 PowerSteering 为 2.1.0，SeaweedFS 为 4.18。

部署使用已有 `packages/dps-0.9.0.tgz`，参考 [DPS 0.9 官方部署指南](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html)。SDK 只提供硬件模拟，没有执行 DPS deploy/setup。访问与当前集成状态见 [dps-access.md](dps-access.md)。

## 组件与布局

| 组件 | 当前版本 / 状态 | 配置或入口 |
|---|---|---|
| K3s / Kubernetes | 1.34.12+k3s1 / 1.34.12，原生单节点 Ready | 物理 node `l20-12`、InternalIP `10.6.131.43`；systemd `k3s` |
| Kubernetes runtime | 独立 containerd 2.2.7-k3s1 | 原生 `k3s ctr` |
| Helm / kubectl | 3.22.0 / 1.34.12 | `packages/tools/bin` 与 `/usr/local/bin` 链接 |
| dpsctl / DPS | 0.9.0 / 0.9.0 | CLI 与服务端 release 匹配 |
| PostgreSQL | 17.11，独立 Compose，运行中 | `10.6.131.43:15432`；数据库/应用角色 `dps` |
| OpenLDAP | 2.6.10（Debian 13 包 2.6.10+dfsg-1），独立 Compose | `ldaps://10.6.131.43:1636`，base `dc=dps,dc=lab` |
| PRS / PowerSteering | DPS 0.9 chart 中的 PowerSteering 2.1.0 | Core `dps.prs.enabled` 与 `power-steering.enabled` 同时启用 |
| S3 | chart 配套 SeaweedFS 4.18 | bucket `dps-prs`，仅集群内 Service，3 个 PVC：1Gi/1Gi/10Gi |
| SDK BMC | 0.9.0，4 rack、72 节点、288 GPU | `hardware-sim` 独立 Docker 容器 |
| Ingress / DNS | Traefik、CoreDNS Ready | `traefik` IngressClass，websecure |
| 存储 | local-path Ready；Core 1Gi 和 3 个 PRS/S3 PVC 已 Bound | 持久数据在 `data/kubernetes/storage`，工作负载日志使用 emptyDir |
| TLS / Secrets | Core/Agent/Ingress、数据库/BMC 与 LDAP bind、CA、client TLS 外部 Secret | `config/tls`、`config/ldap` |

K3s 使用 `config/kubernetes/k3s.yaml`，持久化目录为
`data/kubernetes/k3s`、`data/kubernetes/kubelet`、`data/kubernetes/storage`。
`config/kubernetes/k3s-admin.yaml` 与 `config/kubernetes/kubeconfig.yaml` 权限 600；
项目配置 context 为 `dps-l20-12`，Kubernetes API 为 `https://10.6.131.43:6443`。

systemd `k3s` active 且开机 enabled。PostgreSQL、OpenLDAP 与模拟 BMC 使用 Docker `unless-stopped`；
没有执行主机重启测试。单台物理机承担控制与工作节点角色，本环境没有验证多节点故障切换。

## 连接与安装输入

| 入口 | 已验证内容 |
|---|---|
| Kubernetes `https://10.6.131.43:6443` | 物理节点、systemd 宿主进程、containerd、Ready |
| PostgreSQL `10.6.131.43:15432` | 原生 Pod 的 verify-full/TLS 1.3、SQL/DDL 回滚；DPS 实际数据库连接健康 |
| LDAPS `10.6.131.43:1636` | 可信 TLS、真实用户/组、只读 bind 与备份检查通过；DPS 身份/授权检查见当前 LDAP 报告 |
| BMC `10.6.131.43:18443–18514` | 安装后实际 Agent Pod 网络到 72 BMC 的可信 TLS GET、288 GPU/144 CPU 清单和功率遥测通过；Core 派发需激活拓扑，当前延后 |
| DPS gRPC `api.dps.lab:443` | Core TLS 经 Traefik 透传，CLI 登录、服务端版本与诊断通过 |
| DPS UI `https://ui.dps.lab` | HTTPS、登录、UI 代理版本/拓扑读取和退出通过 |

远端 hosts 已将两个 DPS 域名解析到 `10.6.131.43`。外部客户端需配置解析并信任
`config/tls/ca.crt`，不能将 Kubernetes API 端口当作 DPS API 端口。

安装输入：

- `config/values.yaml`：已安装的 Core/Agent/UI、PRS/PowerSteering 与 S3 values，引用外部数据库和 TLS/BMC/LDAP/S3 Secret。
- `config/topology-4rack-dps09.json`：当前 4-rack 导入/更新文件，72 个 ComputerSystem 的 AgentId 位于 `Topology.Entities` 关系对象，目标 `gb300-lab-agent`。72 条关联已通过官方 API 与当前 hash 校验更新并回读确认。旧版输入仅在 `verification/archive/dps-install/legacy-topology-inputs/` 保留，后续接入只使用当前文件。
- `config/gb300-power-shelf-devices.yaml`：33kW、0.95 效率电源架注册输入。
- `config/bmc-endpoints.csv`、`bmc-credentials.json`、`bmc-shared-secret.yaml`：BMC 地址及共享凭据，权限 600。fixture 不强制认证，具体行为见硬件说明。
- `config/postgresql-credentials.json`、`postgresql-secret.yaml`：独立 PostgreSQL 凭据，权限 600。
- `config/postgresql-ca-secret.yaml`、`bmc-ca-secret.yaml`：数据库和 BMC 信任 CA。
- `config/tls/`：Core、Agent、Ingress 证书与持续使用的 JWT 私钥；CA 私钥不挂载到 Pod。DPS 证书到期 2027-10-09，PostgreSQL 证书到期 2028-10-08。
- `config/runtime-images.json`：固定 Core/Agent/UI 与 PostgreSQL migration 客户端镜像 digest，已在原生 containerd 预置。migration 客户端不是独立数据库服务。
- `config/ldap/compose.yaml`、`slapd.conf`、`bootstrap.ldif`：独立目录配置，初始数据仅在空目录创建。
- `config/ldap/credentials.json`：目录管理、只读 bind 和目录用户凭据，权限 600，不写入 Markdown 或普通日志。
- `config/ldap/dps-ldap-bind-secret.yaml`：Secret `dps-ldap-bind` 的 `bind-password`，用于 `uid=dps-bind,ou=services,dc=dps,dc=lab` 的只读搜索。
- `config/ldap/dps-ldap-ca-secret.yaml`、`dps-ldap-client-tls-secret.yaml`：Secret `dps-ldap-ca`/`dps-ldap-client-tls`，挂载 `/secrets/ldap/ca.crt`、`tls.crt`、`tls.key`。
- `config/ldap-auth-migration.json`：LDAP 配置/JWT 一次性轮换状态，重跑保留已完成的轮换。
- `config/dps-access.json` 与 `config/dpsctl/credentials.yaml`：真实 LDAP 管理员用户与 CLI 凭据，权限 600。

`values.yaml` 使用独立 LDAP 密码认证、直接 BMC 和 Agent mTLS；`dcpower-users` 组映射 admin，组外用户没有默认权限。组外真实用户可以获得 roles=[]、memberOf=[] 的令牌，受保护 RPC 拒绝其访问；不能将其描述为 LDAP 登录或令牌签发被拒绝。PRS 和 PowerSteering 已同时开启，`global.prs_enabled` 已设置 true。关闭 chart 内置 PostgreSQL、OIDC、Zapp 与依赖 Zapp 的 excursion mitigation。PRS 使用独立 PG 三个库和集群内 SeaweedFS S3；4-rack 拓扑已导入并在 UI 可见，
保持 inactive。Agent mTLS 已连接，但 inactive 拓扑尚不下发设备配置；DPS 拓扑连接和深层 BMC 健康检查需激活后执行。当前激活会应用 MaxLPS 功率策略，本次没有执行，DPS 硬件集成验收延后。

DPS 0.9 Core 启动要求配置 LDAP client cert/key。独立 `dps-ldap-client` clientAuth 证书由 `prepare-ldap-client-tls.py` 准备，`configure-ldap-auth.py` 自动调用该入口。它满足 Core 的配置要求；LDAP 用户仍通过密码和组成员关系认证/授权，不表示 OpenLDAP 强制双向 TLS。

## PRS 依赖与当前边界

三个数据库 `dps_prs_config`、`dps_prs_config_staged`、`dps_prs_controller` 均由独立 PostgreSQL 17.11 中的非 superuser 角色 `dps` 拥有，migration 权限已准备。TLS 使用 `PGSSLMODE=verify-full`、`PGSSLROOTCERT=/secrets/postgresql/ca.crt`；凭据继续引用外部 Secret，不写入普通 values。

SeaweedFS 4.18 的 bucket 为 `dps-prs`，S3 凭据在 `config/prs/s3-credentials.json`，通过 `dps-prs-s3` 提供给服务。新增的三个 local-path PVC 为 1Gi/1Gi/10Gi，持久数据在项目 `data/kubernetes/storage`；工作负载日志使用 emptyDir。没有 S3 外部 Ingress。Controller 使用 `dps-prs-dps-auth` 的 `ldap-credentials` JSON 以真实 `dps-lab` 用户和严格 DPS gRPC TLS 连接 Core。

独立 PostgreSQL 经 Docker 端口映射转发到 `172.30.90.2:5432`，实际 PRS NetworkPolicy 已包含该转发地址和端口。首次 PRS 升级的连通性故障及修复记录在 installstep.md，Config 的历史 6 次重启保留在验收记录中。

数据库准备说明见 [PRS 数据库](config/prs/database-prerequisites.md)，LDAP 维护说明见 [独立 LDAP](config/ldap/README.md)。当前没有资源组，Config API 的 domain 列表为空；已有 4-rack 拓扑保持 inactive。启用、Ready 或空列表不等于动态功率分配/控制已通过，不激活拓扑或写 BMC。

## 日常维护

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
./dps-install/scripts/kubernetes.sh status
./dps-install/scripts/postgresql-status.sh
./dps-install/scripts/ldap-status.sh
./hardware-sim/scripts/bmc-simulator.sh status
kubectl --context dps-l20-12 get nodes -o wide
kubectl --context dps-l20-12 -n dps get pods,pvc
helm --kube-context dps-l20-12 -n dps list
dpsctl verify --dps-server --database --auth --ui
```

`dps-env.sh` 固定 kubeconfig、Helm 配置/缓存、dpsctl API/CA/凭据/日志路径，
并导出 `DPS_KUBE_CONTEXT=dps-l20-12`、`DPS_KUBE_NODE=l20-12`。
不要输出 kubeconfig 原文或 Secret 值。

```bash
# 按需启动已停止的前置服务，保留原数据
./dps-install/scripts/kubernetes.sh start
./dps-install/scripts/postgresql-start.sh
./dps-install/scripts/ldap-start.sh
./hardware-sim/scripts/bmc-simulator.sh start

# 独立数据库备份
./dps-install/scripts/postgresql-backup.sh
./dps-install/scripts/ldap-backup.sh
./dps-install/scripts/postgresql-backup-prs.sh
```

`kubernetes.sh stop` 使用 `systemctl stop k3s`，已有 Pod/containerd 任务可能继续运行，
不能据此认定所有 DPS 工作负载或功率控制停止。不要删除 data、PVC 或数据库卷来重装。
local-path PVC 删除受 reclaimPolicy 约束，数据库备份/恢复见 [PostgreSQL 文档](config/postgresql/README.md)。

## 复现安装

以下是当前有效入口，具体已执行命令与结果见根目录 `installstep.md`：

```bash
cd /raid/vince/deploy
python3 dps-install/scripts/install-tools.py
bash dps-install/scripts/install-dpsctl.sh
bash dps-install/scripts/postgresql-start.sh
bash dps-install/scripts/install-kubernetes.sh
python3 dps-install/scripts/refresh-kubeconfig.py
source dps-install/config/dps-env.sh
python3 dps-install/scripts/prepare-certificates.py
python3 dps-install/scripts/prepare-ldap.py
bash dps-install/scripts/ldap-start.sh
bash dps-install/scripts/ldap-status.sh
python3 dps-install/scripts/configure-ldap-auth.py
python3 dps-install/scripts/prepare-prs-databases.py
python3 dps-install/scripts/configure-prs.py
bash dps-install/scripts/prepare-namespace.sh
python3 dps-install/scripts/stage-runtime-images.py
python3 dps-install/scripts/stage-prs-images.py
bash dps-install/scripts/install-dps.sh
bash dps-install/scripts/dps-login.sh
```

证书脚本正常重跑保留证书/JWT，半缺失或不匹配时拒绝继续。PostgreSQL 初始 SQL 只在空 PGDATA
执行。K3s 安装入口保留符合配置的服务与持久数据。`install-dps.sh` 已执行成功；重跑会做 Helm upgrade，
维护查询无需重跑安装。

`prepare-ldap.py` 从固定的 `packages/ldap/openldap-2.6.10-runtime.tar` 加载镜像；常规复用不执行 `build-ldap.sh`。该脚本仅用于可选源码重建，镜像 ID 变化后须先审查 `config/ldap/deployment.json` 的固定身份。

`configure-ldap-auth.py` 检查独立 LDAP，配置只读 bind 和完整 CA/client TLS，再依据迁移状态一次性轮换 JWT 签名身份。旧会话需重新登录，当前真实用户密码由 `dps-login.sh` 经标准输入提供。OpenLDAP 初始化仅在空 `data/ldap` 执行，重启保留目录数据。

LDAP MDB 支持运行中备份；恢复须停止 LDAP，保留原数据并导入新的空目录，不能在线向生产目录执行 slapadd。已验证 LDAP 备份为 `data/ldap-backups/ldap-20261010T023406Z.ldif`（600）；切换后的 PostgreSQL 备份为 `data/postgresql-backups/dps-20261010T025312Z.dump`，已通过 pg_restore --list。

PRS 升级后已生成 `data/postgresql-backups/dps-20261010T090629Z.dump`，以及 `dps_prs_config-20261010T090629Z.dump`、`dps_prs_config_staged-20261010T090629Z.dump`、`dps_prs_controller-20261010T090629Z.dump` 三份 PRS 数据库备份，均为权限 600；没有执行恢复覆盖生产库。

对应的显式 Helm 命令为：

```bash
helm upgrade --install dps dps-install/packages/dps-0.9.0.tgz \
  --kube-context dps-l20-12 --namespace dps \
  --values dps-install/config/values.yaml --wait --timeout 10m
```

CLI 登录后，`register-devices.sh` 准备电源架规格，`import-topology.sh` 用于首次导入；
当前同名拓扑已经存在，不要重复首次导入。`update-topology.sh` 通过官方 API 与当前 hash 校验更新已有 inactive 拓扑，
不激活、不更改策略、不执行功率控制。

PRS 数据库准备只补齐上述三个库、owner/public migration 权限和明确可信网段的 hostssl SCRAM HBA，保留原 DPS 数据库。`configure-prs.py` 准备双启用 values 与私密 S3/DPS 用户 Secret，`stage-prs-images.py` 根据固定 manifest 导入原生 containerd。Helm 升级部署组件，运行时 PRS 标志以现行验收报告为准；安装步骤见根目录 installstep.md。

## 验证与历史记录

安装前的 19 项原生检查报告为 `verification/reports/prerequisite-check.json`，
日志为 `verification/logs/native-k3s-prerequisite-check.log`。其中“无 DPS release/无 PV”
是安装前的快照，当前已安装 DPS 且 Core PVC Bound；该前置脚本要求 release 尚不存在，
不能将它作为安装后的整体验收入口。

2026-10-09 安装后通过 `verification/scripts/verify-agent-pod-bmc.py`，从实际 Agent Pod 的网络 namespace 使用 nsenter 发出 1152 次 GET：72 个唯一 BMC 全部 HTTPS CA 校验成功，4 rack 各 18 节点，288 GPU 与 144 CPU 清单/功率遥测正常。报告为 `verification/reports/dps-pod-bmc-connectivity.json`；没有修改 Pod spec、创建临时容器或写入 BMC。这是网络/Redfish 验证，不代表 Core→Agent→BMC 派发通过。

PRS 数据库先决条件报告为 `verification/reports/prs-databases.json`（18/18），属于独立 PG/实际 EngineFactory 的 host-network 探针，不证明实际 PRS Pod Ready。实际 Pod、S3/PVC、Core PRS 标志与 API 验收见 `verification/reports/prs-installation.json`。

当前部署以 `verification/reports/dps-current-state.json`、`dps-delivery-status.json` 和 PRS 验收报告为准；LDAP 28 项保留上午切换时的完整认证验收范围；备份校验见 `dps-post-ldap-backup.json`。通用服务复验入口为 `verification/scripts/verify-dps-installation.py`，现存 `dps-installation.json` 的 17 项与 `dps-ui-topology.json` 的 8 项是 2026-10-09 初始安装历史。独立 LDAP 检查为 `verify-ldap.py`/`ldap-installation.json`（18/18）；2026-10-10 上午 LDAP 身份、授权和旧令牌撤销检查为 `verify-ldap-auth.py`/`dps-ldap-auth.json`（10:52:29+08，28/28），该完整认证结果保留其当时范围。UI 拓扑可见性、连接及 BMC 深层检查
分别保存在 `dps-ui-topology.json`、`dps-topology-connection.json`、`dps-bmc-health.json`；
各报告按实际时间与范围判断。验证文件只用于检查，不是安装输入。

迁移前说明位于 `verification/archive/native-k3s-migration/docs/`；
初始安装前文档位于 `verification/archive/dps-install-docs/`；初始认证说明在 `verification/archive/ldap-auth-migration/docs-before-ldap/20261010T103902+0800/`，不作为当前认证方案。
