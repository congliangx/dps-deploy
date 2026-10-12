# 部署验证与历史记录

本目录的脚本用于确认部署是否正确，报告用于查看结果和追溯。模拟器运行、DPS Helm 安装、
设备注册和拓扑导入不读取这些报告。

当前 DPS 0.9.0 已安装在 L20-12 原生 K3s 物理单节点 `l20-12`，
context `dps-l20-12`、namespace `dps`、release `dps`。Core/Agent/UI 均 1/1 Ready，
2026-10-10 上午（Asia/Shanghai）目录 18 项检查通过；10:52:29 的 DPS LDAP 身份/授权、令牌与 UI session API 验收为 28/28，UI 未进行浏览器视觉验收。4-rack 拓扑已导入、UI 可见、保持 inactive；
Agent mTLS 已连接，inactive 时尚不下发设备配置。DPS 拓扑连接和深层 BMC 健康检查需要激活拓扑，而当前激活会应用 MaxLPS 功率策略，本次没有执行，完整硬件集成验收延后。

## 新实例从零部署验收（2026-10-12）

[从零安装入口](../dps-install/from-zero.md) 不自动执行验证。本次空源码副本生成的新密码/CA/JWT/13 Secret、独立 BMC/PG/LDAP 与 DPS/PRS 全栈验收为 44/44；独立 PG 新建链 33/33、LDAP 新建链 24/24。重复完整安装退出成功，46 份身份文件不变、数据库 sentinel 保留后清理。精简公开证据见 [from-zero-summary.json](reports/from-zero-summary.json)。

~~~bash
python3 verification/scripts/verify-cold-bootstrap.py --root /path/to/this-fresh-repo
~~~

该脚本读取本实例 bootstrap-settings.json 和受限凭据，检查严格 TLS 的 72 个 BMC、数据库、LDAP 正负登录、9 Ready 工作负载、PRS/S3 集成和实际存储的 AgentId。默认 CLI 凭据保持不变；临时 UI 会话注销、S3 对象删除。报告留在目标 root/verification/reports/cold-bootstrap-fullstack.json（600）；不部署、激活拓扑或写 BMC 功率。新脚本适用于从零入口生成的实例，不能替代旧实例维护验收入口。

本轮全栈复用了 L20-12 已有物理机原生 K3s；未在空白 OS 上执行系统软件/K3s 首次安装。默认原生配置和下载/重定位链另做源码与格式检查，不把该检查等同于裸机首次运行验收。测试日志、详细报告与试验身份仅在 verification/archive/cold-bootstrap 保留，不推 Git。

## 当前 PRS 部署检查

PRS 对应实际 DPS 0.9 chart 中的 PowerSteering 2.1.0。独立数据库先决条件在 `reports/prs-databases.json`（18/18）检查三个库的 owner/ACL、EngineFactory/SQLAlchemy/psycopg2 严格 TLS 与错误条件；探针在 host-network 镜像内执行，不代表实际 PRS Pod 验收。

当前部署验收报告是 `reports/prs-installation.json`：2026-10-10T17:05:41.804854+08:00，35/35 通过，涵盖 9 个 workload Ready、Helm revision 5、实际 PRS Pod 的 verify-full PostgreSQL 连接、S3 授权读写/匿名拒绝、Controller 真实 LDAP 与严格 DPS TLS 读取，以及 DPS 登录回归。验收仅覆盖部署/连接/存储/API/PRS flag。Config 首次升级的历史 6 次重启如实保留，最终 workload Ready；运行日志使用 emptyDir。无资源组和 PRS domain、topology inactive，未验证动态功率分配、策略执行或 BMC 控制。

## 当前 DPS 安装检查

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
python3 verification/scripts/verify-dps-installation.py
```

该脚本检查 Helm release、Core/Agent/UI Ready、PVC、外部数据库/认证健康、CLI 和服务端版本、
Agent mTLS 会话、UI HTTPS、登录、UI 代理和退出。它使用受限的 `config/dps-access.json`
执行真实 LDAP 登录并写入项目 `config/dpsctl/credentials.yaml`，不打印密码或 token。
不导入/激活拓扑、不执行硬件功率写入。运行结果见 `reports/dps-installation.json`；2026-10-09 初始安装结果属于历史，当前认证以 2026-10-10 LDAP 报告为准。

2026-10-09 UI 拓扑检查已确认 110 实体、72 ComputerSystem、每 rack 18 个节点及 inactive。
AgentId 必须存在于 `Topology.Entities` 关系对象；仅在 inventory Entities 元数据中出现，
不能作为设备路由成功证据。官方 API 与当前 hash 校验更新已成功，原始 GetTopologyModel 回读确认 110 条关系中的 72 个计算节点 AgentId 为 `gb300-lab-agent`。CLI topology export 会省略此字段，不能用其判断关联是否存储成功。inactive 拓扑尚不下发设备配置，assigned_devices=0 属于此状态；DPS 连接和 BMC 深层检查在激活前无法启动，现有返回不能列为通过，也不等价于网络连接失败。

2026-10-09 安装后的实际 Agent Pod 网络验证通过 `scripts/verify-agent-pod-bmc.py`：通过 nsenter 进入现有 Pod 的网络 namespace，72 个唯一 BMC 全部 HTTPS CA 校验成功，4 rack 各 18 节点，288 GPU 和 144 CPU 清单/功率遥测正常，共 1152 次 GET。未修改 Pod spec、未创建临时容器、未发送 BMC 写请求。结果为 `reports/dps-pod-bmc-connectivity.json`，只证明 Agent Pod 到 BMC 网络/Redfish，不代表 Core→Agent→BMC 派发已通过。

## LDAP 目录与 DPS 身份/授权历史验收

独立目录入口 `scripts/verify-ldap.py` 和报告 `reports/ldap-installation.json`（18/18）检查可信 LDAPS、用户/组、错误/匿名凭据拒绝及只读 bind 权限。`reports/ldap-backup.json` 记录 8 条目 LDIF、权限 600 和离线 `slapadd -u`，没有恢复覆盖生产数据。

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
python3 verification/scripts/verify-ldap-auth.py
```

2026-10-10T10:52:29+08 的报告 `reports/dps-ldap-auth.json` 为 28/28：UI session API 登录 200、Cookie、拓扑读取 200、退出 204；错密码/不存在账号 401、空密码 400，均无 token/cookie；组外身份登录 200，但受保护 UI API 403/CLI AUTHORIZATION_FAILED；旧 access/refresh 均 401，新 refresh 200。UI 通过会话 API 验证，没有浏览器视觉验收。测试 session 已注销。

该报告检查真实 admin 用户 CLI/UI 登录、JWT admin 角色/组、错误/不存在/空密码拒绝、组外真实用户的受保护接口授权失败、旧 access/refresh 令牌失效及新 refresh/logout。组外账号可以通过 LDAP 身份认证并取得无角色令牌；验证要求其受保护 RPC 被拒绝，不要求令牌签发失败。报告不包含明文密码或令牌。

## 安装前的前置检查

`verify-prerequisites.py` 用于安装 DPS 前的验收，19 项原生结果保存在
`reports/prerequisite-check.json`，日志为 `logs/native-k3s-prerequisite-check.log`。
检查涵盖物理节点身份、systemd 宿主进程/containerd、基础组件、Secret/证书、Helm 渲染、
原生 Pod 到 PostgreSQL 的 verify-full/TLS 1.3/SQL/DDL 回滚、72 BMC/288 GPU 的可信 TLS GET、
DNS 和 1Gi PVC 读写。测试资源已清理。

该脚本硬性要求 DPS release 不存在；当前安装后运行会在这一条件失败，不作为当前安装验收入口。
“无 release/无 PV”也仅代表安装前快照。数据库事务 DDL 检查只证明基本权限，
不是 DPS migration 成功的替代证据。

`postgres-verify.py` 用于独立数据库宿主机 TLS、认证和权限检查；
`stage-probe-images.py` 只为验证准备 probe 镜像，正式交付安装由
`dps-install/scripts/stage-runtime-images.py` 管理。

## 模拟器可选验证

```bash
cd /raid/vince/deploy
# 只读：72 节点 Redfish 清单、遥测与拓扑映射
./verification/scripts/verify-simulator.sh

# 临时改变 72 节点 GPU_0 功率限制，再读回并恢复
./verification/scripts/verify-simulator.sh --control
```

默认只读，结果进入 `reports/` 与 `logs/`。`--control` 是独立模拟控制验证，
不要在 DPS 正在控制节点功率时执行。模拟器可读写成功不能单独证明 DPS 的策略执行成功。

## 报告用途

| `reports/` 中的文件 | 用途 | 安装是否需要读取 |
|---|---|---|
| `dps-current-state.json` | 当前物理节点、release、LDAP/PRS Ready 与 inactive 拓扑快照，按报告时间判断 | 不需要 |
| `prs-installation.json` | PRS/PowerSteering 实际 Pod、严格 DB TLS、S3/PVC、Core flag 与只读 API 验收 | 不需要 |
| `prs-databases.json` | 独立三库先决 18/18，host-network EngineFactory 探针 | 不需要 |
| `prs-render.json` | PRS/PowerSteering/S3 配置、镜像、PVC 和外部 Secret 的 Helm 渲染 | 不需要 |
| `dps-delivery-status.json` | 当前 PRS 交付汇总，LDAP/初始历史与 inactive 下待验收范围分别记录 | 不需要 |
| `dps-post-ldap-backup.json` | LDAP 切换后的 PostgreSQL 备份及 pg_restore --list 校验 | 不需要 |
| `dps-installation.json` | 2026-10-09 初始安装 17/17 历史；通用复验脚本已适配真实认证 | 不需要 |
| `ldap-installation.json`、`ldap-backup.json` | 2026-10-10 上午独立 LDAP 18 项和 8 条目备份历史验收 | 不需要 |
| `dps-ldap-auth.json` | 2026-10-10T10:52:29+08 LDAP 28/28 历史，保留身份/授权、旧令牌和会话流程的原范围 | 不需要 |
| `dps-ldap-render.json` | LDAP Secret、完整 CA/client TLS 和独立目录配置渲染 | 不需要 |
| `dps-install-rendered.yaml`、`dps-installation-methods.json` | 本次安装渲染与方法审核快照 | 不需要 |
| `dps-ui-topology.json` | 2026-10-09 UI 拓扑 8/8 历史；当前 LDAP UI 验收见 dps-ldap-auth.json | 不需要 |
| `dps-topology-connection.json`、`dps-bmc-health.json` | inactive 状态下无法启动的 DPS 连接/深层 BMC 检查返回，完整验收延后 | 不需要 |
| `dps-pod-bmc-connectivity.json` | 实际 Agent Pod 网络 namespace 到 72 BMC 的 1152 次 HTTPS CA/清单/遥测 GET，只读，不证明 Core 派发 | 不需要 |
| `topology-agent-routing-fix.json` | AgentId 从 inventory 移到 topology 关系对象的修正证据 | 不需要 |
| `topology-agent-routing-stored.json`、`topology-agent-routing-raw-model.json` | 官方 API 回读确认 110 条关系/72 条 Agent 路由及 inactive，原始数据不含 token | 不需要 |
| `topology-dps09-preparation.json`、`gb300-power-shelf-registration-plan.json` | DPS 0.9 输入转换和电源架注册准备追溯 | 不需要 |
| `topology-generator-dps09.json` | 生成器默认输出 DPS 0.9 输入、无旧 Policies、72 条关联与当前输入等价的只读检查 | 不需要 |
| `topology-check.json` | 离线唯一性、计数、引用、连通性、无环检查 | 不需要 |
| `verification-inventory.json` | 72 节点 Redfish 清单和遥测 | 不需要 |
| `verification-control.json` | 模拟功率 PATCH、隔离、恢复和认证行为 | 不需要 |
| `artifact-versions.json` | 模拟器镜像 digest、SDK commit、chart hash | 不需要 |
| `deployment-status.json` | 历史容器状态快照，实时状态通过组件入口查询 | 不需要 |
| `reorganization.json` | 迁移映射、输入 hash、备份位置 | 不需要 |
| `prerequisite-check.json` | 安装前的原生集群/Pod/数据库/BMC/PVC 检查 | 不需要 |
| `prereq-chart-audit.json`、`prereq-render-audit.json`、`dps-prereq-rendered.yaml` | 前置阶段 chart 审核与渲染 | 不需要 |
| `tool-installation.json` | 官方下载来源、版本、SHA256 | 不需要 |
| `certificate-rerun-check.json` | 证书/JWT 重跑身份保持与拒绝不完整证书 | 不需要 |
| `postgres-install-summary.json`、`postgres-host-verification.json` | 数据库安装追溯与宿主机检查 | 不需要 |

实际接入文件是 `../dps-install/config/topology-4rack-dps09.json` 和
`gb300-power-shelf-devices.yaml`。DPS 接入不遍历本目录，也不依赖测试脚本。

## 历史材料

`logs/` 保存下载、安装和检查日志，`archive/` 保存历史备份。
原生迁移资料位于 `archive/native-k3s-migration/`；本次安装前交付文档位于
`archive/dps-install-docs/`。旧容器节点的 context、节点数和端口只反映历史环境。
LDAP 切换前六份说明位于 `archive/ldap-auth-migration/docs-before-ldap/20261010T103902+0800/`，旧评估认证不是当前方案。根目录 `installstep.md` 是当前有效安装步骤和实际执行记录。

PRS 启用前配置和六份说明保存在 `archive/prs-enablement/20261010T164346+0800/`。

报告是带时间和检查范围的快照。查看当前运行状态时使用 kubectl、Helm、dpsctl 和组件维护入口，
不能凭一个历史 JSON 判断当前集群或硬件控制状态。
