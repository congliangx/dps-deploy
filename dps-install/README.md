# DPS 0.9 安装文件与运行环境

远端工作目录 `/raid/vince/deploy/dps-install`。DPS 0.9.0 通过手动 Helm 部署在物理节点上，release `dps`、namespace `dps`、context `dps-l20-12`。2026-10-10 上午（Asia/Shanghai）接入独立 OpenLDAP 2.6.10；10:52:29 的 DPS LDAP 身份/授权、令牌和 UI session API 验收为 28/28。UI 验证基于会话 API，未进行浏览器视觉验收。SDK 没有安装 DPS。

2026-10-10（Asia/Shanghai）PRS 已通过手动 Helm 升级启用，当前 release 为 revision 5、deployed，9 个 workload Ready。17:05:41 的 PRS 验收为 35/35，覆盖部署、实际 Pod 严格数据库 TLS、S3、Controller 的 LDAP/DPS TLS 连接与登录回归。DPS 已持久化 `prs_enabled=true`、headroom `-15%` 和 scheduler `5 秒`；实际 PowerSteering 为 2.1.0，SeaweedFS 为 4.18。

4-rack 拓扑 `dps-gb300-4rack` 已导入，110 个实体、72 个计算节点在 UI 可见，保持 inactive。2026-10-09 实际 Agent Pod 网络 namespace 到 72 BMC 的 HTTPS/CA、288 GPU/144 CPU 清单与功率遥测检查通过，共 1152 次只读 GET，未修改 Pod spec 或 BMC。该检查不证明 Core→Agent→BMC 派发。官方 API 与当前 hash 校验更新后已回读确认 72 条节点关联的 AgentId。Agent 已通过 mTLS 连接；inactive 拓扑尚不下发设备配置。DPS 拓扑连接和深层 BMC 健康检查需激活后执行，本次没有应用激活时的 MaxLPS 功率策略，相关验收延后。

当前状态报告为 `../verification/reports/dps-current-state.json` 和 `dps-delivery-status.json`；备份校验为 `dps-post-ldap-backup.json`。初始服务/UI/Agent Pod 网络结果保留为 2026-10-09 历史，保留其当时验证范围。

访问与登录见 [dps-access.md](dps-access.md)，前置安装和维护见 [prerequisites.md](prerequisites.md)，实际操作记录见 [installstep.md](../installstep.md)。

| 路径 | 用途 |
|---|---|
| `packages/dps-0.9.0.tgz` | 已复用的 DPS 0.9 Helm chart |
| `packages/tools/` | 官方下载包、校验材料和 Helm/kubectl/dpsctl 二进制 |
| `config/values.yaml` | 已安装的 Core/Agent/UI、PRS/PowerSteering 和 S3 values，仅引用 Secret |
| `config/dps-env.sh` | Kubernetes/Helm/dpsctl 项目环境 |
| `config/dps-access.json` | DPS 管理员 `dps-lab` 的真实 LDAP 登录凭据，权限 600 |
| `config/dpsctl/credentials.yaml` | CLI 登录凭据，文件 600、目录 700 |
| `config/kubernetes/k3s.yaml` | 物理机原生 K3s 配置 |
| `config/kubernetes/k3s-admin.yaml`、`kubeconfig.yaml` | 原始/项目管理员配置，权限 600；项目 context 为 `dps-l20-12` |
| `config/postgresql/`、`config/postgresql-*.yaml` | 独立数据库配置、初始化、证书、凭据 Secret 和 values overlay |
| `config/postgresql-credentials.json` | 数据库专用凭据，权限 600 |
| `config/ldap/` | 独立 OpenLDAP Compose、初始化目录、受限凭据、LDAPS TLS、bind/CA/client TLS Secret |
| `config/ldap-auth-migration.json` | LDAP 配置和一次性 JWT 签名身份轮换状态 |
| `config/prs/prepare-databases.sql`、`databases.json` | 独立 PG 的三个 PRS 库、角色/ACL 与严格 TLS 准备输入 |
| `config/prs/database-prerequisites.md` | PRS 独立数据库维护与备份说明 |
| `config/prs/runtime-images.json`、`enablement.json` | 固定 PRS/S3 镜像和启用配置记录 |
| `config/prs/s3-credentials.json`、`s3-secret.yaml` | S3 私密凭据和外部 Secret `dps-prs-s3`，权限 600 |
| `config/prs/dps-auth-secret.yaml` | PRS Controller 使用真实 LDAP 用户登录 DPS 的 JSON Secret `dps-prs-dps-auth`，权限 600 |
| `config/tls/` | Core/Agent/Ingress TLS、公开 CA、JWT 和 Secret；私钥权限 600 |
| `config/topology-4rack-dps09.json` | 当前 DPS 0.9 导入/更新输入；去除旧 Policies，72 节点 AgentId 位于 Topology.Entities |
| `config/gb300-power-shelf-devices.yaml` | GB300 33kW、效率 0.95 电源架设备注册输入 |
| `config/bmc-endpoints.csv`、`bmc-credentials.json`、`bmc-shared-secret.yaml` | BMC 地址和共享凭据，权限 600 |
| `config/simulator-ca.crt`、`bmc-ca-secret.yaml` | 模拟器公开 CA 和 Kubernetes 信任 Secret |
| `config/runtime-images.json` | 固定 Core/Agent/UI 和 PostgreSQL migration 客户端镜像 digest |
| `scripts/` | 前置安装、手动 Helm 安装、拓扑接入和维护脚本 |
| `data/postgresql`、`data/postgresql-backups` | 独立数据库数据和备份 |
| `data/ldap`、`data/ldap-backups` | 独立目录数据和权限 600 的 LDIF 备份 |
| `packages/ldap/openldap-2.6.10-runtime.tar` | 固定 Debian 13/OpenLDAP 2.6.10 离线运行镜像 |
| `data/kubernetes/{k3s,kubelet,storage}` | 原生 Kubernetes 和 local-path 持久数据 |

原生 K3s/Kubernetes 为 1.34.12+k3s1/1.34.12，物理节点 `l20-12`，containerd 2.2.7-k3s1。Kubernetes API 是 `https://10.6.131.43:6443`；DPS gRPC/TLS API 是 `https://api.dps.lab:443`。独立 PostgreSQL 17.11 位于 `10.6.131.43:15432`，不属于 DPS Helm release。Core PVC 已 Bound。

当前功能范围为 Core、Agent、UI、直接 BMC 和 PRS/PowerSteering 2.1.0 部署。LDAP 使用独立 OpenLDAP 2.6.10，`dcpower-users` 组映射 admin；PRS 与 PowerSteering 已启用，三个 PG 库独立于 Helm release；SeaweedFS 4.18 的集群内 S3 bucket 为 `dps-prs`。OIDC、Zapp、chart 内置 PostgreSQL 保持关闭，拓扑未激活，无资源组或 PRS domain，动态功率尚未验证。安装、启停和拓扑输入不依赖 `../verification/` 中的验收报告。
