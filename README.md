# DPS 0.9 与 GB300 模拟环境

主机 `root@L20-12`，项目目录 `/raid/vince/deploy`。DPS 0.9.0 通过保存的 Helm chart 手动运行在物理机原生 K3s，release `dps`、namespace `dps`、context `dps-l20-12`。2026-10-10 上午（Asia/Shanghai）接入独立 OpenLDAP 2.6.10；10:52:29 的 DPS LDAP 身份/授权、令牌和 UI session API 验收为 28/28。UI 验证基于会话 API，未进行浏览器视觉验收。

2026-10-10（Asia/Shanghai）PRS 已通过手动 Helm 升级启用，当前 release 为 revision 5、deployed，9 个 workload Ready。17:05:41 的 PRS 验收为 35/35，覆盖部署、实际 Pod 严格数据库 TLS、S3、Controller 的 LDAP/DPS TLS 连接与登录回归。DPS 已持久化 `prs_enabled=true`、headroom `-15%` 和 scheduler `5 秒`；实际 PowerSteering 为 2.1.0，SeaweedFS 为 4.18。

SDK 独立模拟 4 个 GB300 rack、72 个计算节点、288 个 GPU；独立 PostgreSQL 17.11 继续运行。2026-10-09 实际 Agent Pod 网络 namespace 到全部 72 个 BMC 的 HTTPS/CA、288 GPU 和 144 CPU 清单/功率遥测检查通过，共 1152 次只读 GET；该结果验证网络与 Redfish，不代表 Core→Agent→BMC 派发已通过。拓扑 `dps-gb300-4rack` 已导入，110 个实体、72 个计算节点在 UI 可见，保持 inactive。已通过官方 API 与当前 hash 校验更新，并回读确认 72 条节点关联路由至 `gb300-lab-agent`。拓扑保持 inactive，Agent 已连接但尚未下发节点配置。DPS 的拓扑连接和深层 BMC 健康检查要求激活拓扑；当前激活会应用 MaxLPS 功率策略，本次没有执行，相关验收延后。

| 目录 / 文件 | 用途 | 入口 |
|---|---|---|
| `hardware-sim/` | SDK 原件、BMC 配置和启停/生成脚本 | [硬件模拟说明](hardware-sim/bmc-access.md) |
| `dps-install/` | DPS 安装包、安装/维护脚本、配置和持久数据 | [DPS 安装文件说明](dps-install/README.md) |
| `dps-install/dps-access.md` | UI/API、登录、CA、环境变量和当前范围 | [DPS 访问说明](dps-install/dps-access.md) |
| `verification/` | 验证脚本、报告、日志和历史备份 | [验证说明](verification/README.md) |
| `installstep.md` | 当前有效安装步骤与实际操作记录 | [步骤记录](installstep.md) |
| `AGENTS.md` | 后续 agent 的操作约定 | [工作约定](AGENTS.md) |

DPS UI 为 `https://ui.dps.lab`，gRPC/TLS API 为 `https://api.dps.lab:443`；客户端需将两个域名解析到 `10.6.131.43` 并信任项目 CA。DPS 管理员（LDAP 用户）为 `dps-lab`，密码在 `dps-install/config/dps-access.json`（600）。`dcpower-users` 组映射 admin；真实组外用户即使通过身份认证，也没有受保护 DPS 接口权限。旧会话需重新登录。

在远端查看状态：

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
kubectl --context dps-l20-12 -n dps get pods,pvc
helm --kube-context dps-l20-12 -n dps list
dpsctl server-version
dpsctl agent list
dpsctl topology list
./dps-install/scripts/kubernetes.sh status
./dps-install/scripts/postgresql-status.sh
./dps-install/scripts/ldap-status.sh
./hardware-sim/scripts/bmc-simulator.sh status
```

Kubernetes 是原生 K3s 1.34.12+k3s1，物理单节点 `l20-12`、InternalIP `10.6.131.43`，由 systemd 管理并使用 containerd 2.2.7-k3s1。Docker 分别运行独立 PostgreSQL、OpenLDAP 和 BMC 模拟器。DPS Core 的 1Gi local-path PVC 已 Bound。LDAP 接入独立 OpenLDAP 2.6.10；PRS 与 PowerSteering 2.1.0 已启用；OIDC、Zapp 与 chart 内置 PostgreSQL 保持禁用。

BMC 地址及凭据位于 `dps-install/config/bmc-endpoints.csv` 和 `bmc-credentials.json`；数据库凭据位于 `postgresql-credentials.json`。这些文件权限 600，普通文档和日志只引用文件位置。

PRS 复用独立 PostgreSQL 17.11 的 `dps_prs_config`、`dps_prs_config_staged`、`dps_prs_controller` 三个库，使用 verify-full。SeaweedFS 4.18 提供集群内 S3，bucket `dps-prs`，新增 PVC 为 1Gi、1Gi、10Gi，持久数据位于项目 storage，日志使用 emptyDir；未配置外部 Ingress。拓扑仍 inactive，无资源组/PRS domain，动态功率闭环尚未验证。

目录端点为 `ldaps://10.6.131.43:1636`，base DN `dc=dps,dc=lab`；独立 LDAP 的 18 项验收及备份检查通过。配置、凭据和证书在 `dps-install/config/ldap/`，持久数据在 `dps-install/data/ldap/`。

本轮 PRS 验收见 `verification/reports/prs-installation.json`。当前运行快照见 `verification/reports/dps-current-state.json` 与 `dps-delivery-status.json`；切换后备份校验见 `dps-post-ldap-backup.json`。2026-10-09 的初始服务、UI 和 Agent Pod 网络结果属于历史快照。

安装和拓扑导入不读取 `verification/reports/` 的报告。安装前 19 项原生前置检查属于历史快照；当前状态以安装验收和实时服务查询为准。旧容器节点和相关交付脚本已退役，原件仅在 `verification/archive/` 保留。根目录 `bmc-access.md` 是保留的兼容链接。

## Git 交付范围

版本库保存必要安装/维护脚本、可复验的验证脚本、当前拓扑与电源架输入、经审查的普通配置、[公开 values 示例](dps-install/config/values.example.yaml)，以及 `verification/reports/` 中最新精简验收摘要。普通配置包括 Compose、原生 K3s 配置、数据库初始化/访问规则和固定镜像 manifest；实际交付以 Git 文件清单为准。

网络下载的镜像/安装包/工具、SDK/vendor、运行数据和数据库备份均不入 Git。真实 `values.yaml`、凭据/Secret、TLS 证书与私钥、JWT、kubeconfig、LDAP 密码哈希及本机迁移/部署状态只在远端保留。`verification/logs/`、`archive/`、旧报告、原始明细和渲染 YAML 也不默认追踪。精简报告或说明引用的这些文件，仍可在 L20-12 的 `/raid/vince/deploy` 查阅。

`dps-install/packages/ldap/build/` 中本次编写的 Dockerfile、entrypoint.sh 与 SHA256SUMS 可作为构建配方/校验元数据保留；其依赖的 Debian 基础镜像和下载包仍需单独取得。其他安装包与 SDK/vendor 已在远端保留，克隆后须按固定版本来源、校验信息和镜像 manifest 准备，不能凭配置示例完成一键重建。

克隆后先阅读 [AGENTS.md](AGENTS.md)、[安装步骤](installstep.md)、[前置说明](dps-install/prerequisites.md) 和 [脚本入口](dps-install/scripts/README.md)，核对现有服务、依赖包和必要输入。示例保留 L20-12 的主机特定地址与 Secret 引用；私密输入须由相应脚本按文档生成，或从受控来源安全补充，且匹配 Secret 名称和 key。仓库不包含现有 LDAP 用户、数据库及签名/证书身份的完整恢复材料；不要为补齐克隆目录而重跑初始化、删除数据、轮换现有身份或重置正在运行的部署。
