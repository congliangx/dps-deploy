# DPS 0.9 安装与 GB300 模拟环境工作约定

## 目标与当前状态

在 L20-12 上手动安装并验证 NVIDIA Dynamic Power Software（DPS）0.9；DPS SDK 仅模拟 4 个 GB300 rack，不能管理 DPS Helm release。

截至 2026-10-10，物理单节点原生 K3s 上 DPS 0.9.0 Helm release dps / namespace dps / revision 5 deployed；Core、Agent、UI、Power Config/Controller 2.1.0 及 SeaweedFS 4.18 共 9 个工作负载 Ready。独立 PostgreSQL 17.11 与 OpenLDAP 2.6.10 提供数据库及真实身份验证。DPS 持久化 prs_enabled=true，headroom -15%、调度间隔 5 秒；PRS 部署与实际 Pod 集成验收 35/35。上午 LDAP 18/18 与 CLI/UI 认证授权 28/28 作为带时间的历史结果保留。SDK BMC Simulator 提供 4 rack、72 计算节点；拓扑 dps-gb300-4rack 仍 inactive，没有资源组或 PRS domain，未执行动态功率控制。

用户最新要求打开 PRS，替代此前保持 Power Steering/PRS 禁用的约定；已完成服务、数据库、S3 和 DPS 全局开关配置。此前要求独立 OpenLDAP 的授权继续有效。旧安装约定及历史保存在 verification/archive/ldap-auth-migration 与 prs-enablement，不作为当前禁用要求。当前入口为 dps-install/README.md、dps-install/dps-access.md 和 installstep.md。

## 执行位置与目录

- 使用现有 SSH 免密配置：ssh root@L20-12。远程项目目录固定 /raid/vince/deploy。
- 所有部署、包处理、脚本、配置、日志、验证和备份在远程执行。本机只连接及同步本约定。
- 系统软件必需路径按机制安装并记录；项目配置、下载包、运行数据及 systemd 配置副本集中在项目目录。
- hardware-sim/ 保存 SDK、vendor、runtime、硬件模拟启动脚本和 bmc-access.md。
- dps-install/packages/ 保存固定安装包；config/ 保存安装输入、拓扑、Secret、证书和访问凭据；scripts/ 保存必要安装及维护入口；data/ 保存 PostgreSQL、LDAP、K3s 数据和备份。
- verification/scripts、reports、logs、archive 分别保存验收脚本、结果、日志、历史/临时材料。启动模拟器、LDAP、数据库或安装 DPS 不能依赖验证报告，也不自动执行验证脚本。
- 根目录保留 README.md、AGENTS.md、installstep.md；旧 bmc-access.md 兼容链接保留。
- 修改前清点服务和文件并备份，不覆盖原有未审阅配置。完整历史不得丢弃；现行安装步骤不得混入退役命令。

## 官方依据与版本

以远程已下载 dps-install/packages/dps-0.9.0.tgz 和官方 0.9 文档为依据，不猜测参数，不替换为其他 DPS 发布版本。

- 安装：https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/index.html
- 部署：https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html
- 用户与角色：https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/concepts/user_accounts.html
- Secret/证书：https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/tasks/credentials-and-secrets-configuration.html
- SDK：https://docs.nvidia.com/datacenter/dps/versions/0.9/sdk/user/index.html

chart SHA256 为 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef，DPS 与 dpsctl 为 0.9.0，SDK BMC Simulator 为 0.9.0。

## 安装与运行边界

### 手动 DPS 与物理 Kubernetes

- DPS 使用独立维护 values.yaml 和明确 Helm 命令安装；不执行 SDK task deploy、task sdk 或隐式部署 DPS 的 setup/playbook。
- Kubernetes 直接运行于 L20-12 操作系统，原生 K3s v1.34.12+k3s1，systemd k3s，节点 l20-12 / 10.6.131.43。
- 显式使用 kubeconfig dps-install/config/kubernetes/kubeconfig.yaml、context dps-l20-12、namespace dps；API 为 https://10.6.131.43:6443。
- K3s 使用独立 containerd，数据集中 data/kubernetes/{k3s,kubelet,storage}，服务要求 /raid 挂载后启动。
- k3d/kind 容器节点已经退役，相关旧脚本/工具只保留历史。不得恢复为当前部署方式。
- 单物理节点承担控制与工作节点，不能称为多节点高可用验证。BMC、PostgreSQL、LDAP 各自使用独立 Docker Compose，维护 K3s 时不能停止 Docker。

### 独立 PostgreSQL

- 独立 PostgreSQL 17.11，容器 dps-postgresql，10.6.131.43:15432，数据库/应用角色 dps，非 superuser，TLS verify-full、SCRAM、持久化数据。
- chart postgresql.enabled 必须为 false；global.postgresql 配置独立数据库及凭据 Secret。
- 初始化只针对空数据目录，不重建已有数据库；备份须校验，恢复不得覆盖运行数据。
- PRS 使用独立 PG 中 dps_prs_config、dps_prs_config_staged、dps_prs_controller 三库，Owner dps，应用 Pod 通过 PGSSLMODE=verify-full 和挂载 CA 严格连接；禁止启用 Power Steering 子 chart 内建 PostgreSQL。

### PRS / Power Steering

- dps.prs.enabled=true 与 power-steering.enabled=true 同时配置，使用下载的 DPS 0.9 chart 所含 Power Steering 2.1.0。
- configure-prs.py 准备安装 values、S3 Secret 和 Controller LDAP Secret；stage-prs-images.py 导入固定镜像；prepare-prs-databases.py 准备三库及限定来源 HBA。必要安装脚本不读取 verification。
- S3 使用 chart 内 SeaweedFS 4.18，bucket dps-prs，随机持久凭据，禁止匿名对象读取；服务仅 ClusterIP。3 个 PVC（1Gi、1Gi、10Gi）实际数据均在 data/kubernetes/storage，组件日志 emptyDir。
- Controller 复用真实 dps-lab LDAP 用户，通过专用 Secret dps-prs-dps-auth 取凭据并严格验证 DPS CA；不关闭 TLS 或认证。
- Config/Controller 网络策略显式允许 PG 宿主机 10.6.131.43:15432 和 Docker DNAT 172.30.90.2:5432；Controller 允许宿主机 API 6443 读取自身凭据 Secret。PG 会话在服务端可呈现 Docker SNAT 来源 172.30.90.1。
- Helm values 不能覆盖已有数据库的全局用户设置；启用时已显式执行 dpsctl settings update --set prs_enabled=true 并读回。当前 headroom -15%、调度间隔 5 秒，禁止无理由调整。
- 调度器周期之间 idle 是正常状态。当前没有 active topology、resource group 或 domain；服务就绪与登录/S3/数据库集成通过，不等于已验证自动功率闭环。
- config/prs/README.md 保存本组件维护入口；备份包括 Core 数据库和三个 PRS 数据库。历史失败 revision 4、修复后 revision 5 及 Config 初次失败累计重启保留真实记录。

### 独立 OpenLDAP 与真实身份验证

- 独立服务 dps-openldap，不连接公司 LDAP，不由 DPS chart 或 SDK 安装。版本 2.6.10；LDAPS ldaps://10.6.131.43:1636，持久化 data/ldap，restart unless-stopped。
- 根 DN dc=dps,dc=lab；真实用户 uid=dps-lab,ou=users,dc=dps,dc=lab；groupOfNames 组 cn=dcpower-users,ou=groups,dc=dps,dc=lab 通过完整 member DN 关联用户。
- DPS 只读 bind DN uid=dps-bind,ou=services,dc=dps,dc=lab，专用随机密码。该账号不能写目录或读取密码哈希。
- DPS authenticatorType 必须为 ldap，ldap.enabled 为 true，OIDC disabled；groupAttribute cn，groupRoleMapping dcpower-users=admin，auth_required_groups dcpower-users，defaultRole 空。
- 用户密码由 LDAP 校验。错误/不存在账号被拒绝；有效组外用户可能获得 roles=[]、memberOf=[] 的令牌，但受保护 DPS RPC 必须拒绝，不能把“令牌签发成功”当作 admin 授权。
- 严格验证 LDAPS CA/主机身份，不开启 LDAP_INSECURE_TLS。当前 Core 实际要求 CA、客户端证书及 key 三个文件均存在，通过 projected.sources[].secret 挂载。客户端证书是 Core 配置要求，不能据此宣称 OpenLDAP 强制双向 TLS。
- 使用 dps-ldap-bind、dps-ldap-ca、dps-ldap-client-tls 三个外部 Secret。密码不放 values 明文。
- 迁移时已一次性轮换 JWT RSA 签名密钥并实际验证旧 alwaysAllow access/refresh 令牌均被拒绝。重跑 configure-ldap-auth.py 只核对已提交密钥，不再轮换；不能手动清空 migration 状态触发新轮换。
- LDAP 配置/凭据在 config/ldap；用户 UI 凭据在 config/dps-access.json；JWT 在 config/dpsctl/credentials.yaml。私密目录 700、密码/私钥/Secret/令牌文件 600，普通文档和日志不记录秘密。

### BMC 接入与拓扑边界

- SDK 仅模拟恰好 4 rack / 72 计算节点 / 288 GPU / 144 CPU；唯一标识和供电引用保持一致。
- 72 个 BMC 入口为 10.6.131.43:18443–18514；清单 config/bmc-endpoints.csv，凭据文件权限 600。模拟器不强制密码且 fixture 存在固定文字/序列号限制，必须如实说明。
- DPS telemetry.metrics.source=bmc，Agent 直接接入 Redfish，不安装 Zapp；excursionMitigation.strategy 空。Power Steering/PRS 已启用；OIDC 保持禁用。
- 拓扑输入 config/topology-4rack-dps09.json，110 实体；72 个 AgentId 路由必须在 Topology.Entities 关系对象。不可使用旧 SDK 非空 Policies 数组。
- 首次 import-topology.sh；已有 inactive 拓扑用 update-topology.sh，经官方 API/current Hash 防冲突。实测 0.9 CLI update 走 create 路径，CLI export 遗漏 AgentId，不能以此证明有效更新/路由。
- PowerSupply95_33000W 由 register-devices.sh 显式注册，不混用 3300 W 型号。
- 当前 topology inactive、MaxLPS。认证维护不激活拓扑、不修改功率策略、不执行 BMC 功率 PATCH。
- Agent connected 与 Pod 到 BMC HTTPS GET 已验证，不代表 Core 经 Agent 的指标/功率闭环验证完成。该集成需要 active topology；不能为只读验收擅自激活。

## 操作顺序与记录

1. SSH 连接，确认主机/工作目录，清点已有服务和包；修改前项目内备份。
2. 复用固定工具、SDK 和 DPS chart，确保物理 K3s Ready，独立 BMC/数据库正常。
3. 独立准备并启动 OpenLDAP；复用已有镜像、用户、密码、目录数据和证书，不重新初始化。
4. configure-ldap-auth.py 准备严格 TLS/LDAP values、Secrets 及已提交 JWT 签名身份；prepare-namespace.sh 应用外部 Secrets。
5. PRS 准备三库、固定镜像、configure-prs.py 和外部 Secret；手动 Helm install-dps.sh；DPS Ready 后 dps-login.sh 使用真实账号从 stdin 登录。
6. 必要时显式设置并读回 prs_enabled；验收脚本只放 verification，认证与 PRS 部署集成分别报告；拓扑保持当前状态。
7. 更新 installstep.md、访问文档、当前状态报告和备份；同步本机 deploy/AGENTS.md。

installstep.md 记录时间/时区、目的、实际命令、版本和路径、成功/失败及修复。现行可复用命令与一次性迁移/排障命令分开；历史失败保留完整证据，不能标记为未失败或将离线渲染当成运行验收。

## 凭据与异常处理

用户 NGC API key 当前只在本机 deploy/.ngc.env（600），未同步/验证；本次镜像匿名获取成功，global.imagePullSecrets 空。后续真正需要认证时才安全复制到 config/.ngc.env，禁止打印或 shell tracing。

遇到故障先记录证据并继续可独立完成的工作。不得删除无关集群、重置宿主机、清空持久化目录或对运行数据库覆盖恢复；涉及新的破坏性动作先提出具体影响。当前用户已授权独立 LDAP、DPS 认证切换及 PRS 服务启用，不能按旧禁用约定中止工作。拓扑激活、资源组创建及功率写入不在本次 PRS 服务启用范围。
