# 首次部署与维护脚本

新主机或空仓库使用 [从零部署说明](../from-zero.md) 和 install-from-zero.sh。默认 root 是脚本所在仓库，可用 --root 指定另一份同内容仓库；host-ip 必填，namespace/release、主机/接口、域名、容器前缀、端口和子网均可指定。首次部署生成独立新身份，下载固定资源，不要求旧 alwaysAllow 认证、原 LDAP tar/镜像 ID 或现有凭据。

## 新实例入口与配置生成

| 脚本 | 用途 |
|---|---|
| install-from-zero.sh | root 用户的公开入口：检查/准备宿主依赖，再执行新实例安装；支持 download-only、prepare-only 和显式 kubeconfig 复用 |
| install-host-dependencies.sh | 准备 Docker/Compose v2、Python YAML、OpenSSL 等宿主依赖，复用已有匹配 Docker；系统包不入 Git |
| install-from-zero.py | 参数/归属检查、下载/生产配置、原生 K3s/工具、独立 Docker 服务、手动 Helm、LDAP 登录、inactive 拓扑导入与 PRS 设置 |
| download-artifacts.py | 按 artifact-sources.json 获取官方 chart、11 个镜像 digest 和 17 个固定 deb；构建 bootstrap LDAP，记录本次新 ID，拒绝冲突缓存 |
| prepare-bmc-fresh.py | 从固定模拟器镜像与公开拓扑生成四 rack/72 BMC 的新凭据、CA、路由与 Compose，不依赖 SDK/vendor |
| prepare-postgresql.py | 新建独立 PG 的随机密码/CA、SCRAM/TLS、Core/PRS 四库输入与 Secret；不覆盖现有非 bootstrap 数据/身份 |
| prepare-ldap-fresh.py | 按本次 LDAP 运行镜像生成新目录用户/组、只读 bind、密码/CA、Compose 和外部 Secret |
| prepare-dps-fresh.py | 生成新 DPS/Agent/UI/JWT/LDAP client TLS、values 和 13 份安装 Secret，直接配置真实 LDAP 与 PRS |

入口顺序为获取资源 → 新实例配置生成 → 原生 Kubernetes/工具 → 独立 BMC/PG/LDAP → 手动 Helm → LDAP 登录 → 电源架注册/四 rack inactive 拓扑 → prs_enabled=true。准备脚本不单独部署 DPS；download-only/prepare-only 不部署应用，但 shell 入口仍检查或准备主机依赖。

2026-10-12 的空仓库隔离新装已通过 44/44，9 workload Ready/0 restart；实际复用已有物理原生 K3s，未覆盖裸机 OS/K3s 首次安装。完整入口再次运行退出 0，46 份身份/Secret 文件保持不变、数据库 sentinel 保留，具体范围见 [from-zero.md](../from-zero.md)。

BMC 与 DPS 默认不执行功率写入；拓扑保持 inactive，0 资源组/PRS domain。安装和网络/服务检查不代表完整 Core→Agent→BMC 派发或动态功率闭环已经通过。

## 现有 L20-12 维护与历史迁移

以下清单用于已运行的 L20-12 /raid/vince/deploy 环境；其机器参数和迁移状态与新实例分开。2026-10-10 原部署 revision 5、9 workload Ready、PRS 集成 35/35；上午独立 LDAP 18/18、DPS 身份/授权/会话 API 28/28 属于当时验收。新实例的阶段与最新验收见 [from-zero.md](../from-zero.md)。

| 脚本 | 用途 |
|---|---|
| `install-tools.py` | 官方下载、SHA256/版本校验，原子安装固定 Helm、kubectl |
| `install-dpsctl.sh` | 从固定官方镜像提取并安装 dpsctl 0.9 |
| `install-kubernetes.sh` | 安装或核对物理机原生 K3s 1.34.12+k3s1、systemd 和项目数据目录 |
| `refresh-kubeconfig.py` | 生成权限 600 的项目 kubeconfig，context 为 `dps-l20-12` |
| `kubernetes.sh status/start/stop` | 通过 systemctl 维护 K3s，保留持久数据 |
| `postgresql-start.sh`、`postgresql-status.sh`、`postgresql-stop.sh` | 独立 PostgreSQL Compose 启停与状态 |
| `postgresql-backup.sh` | 将 DPS 数据库备份到 `data/postgresql-backups`，权限 600 |
| `prepare-prs-databases.py` | 在独立 PostgreSQL 中准备 PRS 的三个数据库、dps 角色权限和限定来源的 hostssl SCRAM 规则，保存必要数据库输入 |
| `postgresql-backup-prs.sh` | 将 PRS 的三个数据库分别备份为权限 600 的 custom dump，保留 DPS 数据库的独立备份入口 |
| `prepare-ldap.py` | 从固定 runtime.tar 加载镜像，准备独立 LDAP 配置、初始化账号、LDAPS TLS 和 bind/CA Secret；已有目录不重置 |
| `build-ldap.sh` | 可选源码重建：用固定 Debian 13 基础镜像构建 OpenLDAP 2.6.10；镜像 ID 变更后先审查 deployment 固定 ID |
| `ldap-start.sh`、`ldap-status.sh`、`ldap-stop.sh` | 独立 OpenLDAP Compose 启停与状态，保留 `data/ldap` |
| `ldap-backup.sh` | 将目录备份为 `data/ldap-backups` 中权限 600 的 LDIF |
| `prepare-ldap-client-tls.py` | 准备独立 LDAP clientAuth 证书和 client TLS Secret，满足 DPS 0.9 Core 的证书/私钥配置要求 |
| `configure-ldap-auth.py` | 检查 LDAP Ready，调用客户端证书准备，配置 LDAP values、只读 bind 与完整 CA/client TLS 投射卷，并一次性轮换 JWT 签名身份 |
| `dps-login.sh` | 从私密账户文件读取真实 LDAP 用户密码，通过标准输入执行 CLI 登录 |
| `prepare-certificates.py` | 准备稳定 TLS/JWT/外部 Secret，拒绝不完整或不匹配的已有证书 |
| `prepare-namespace.sh` | 用明确 context 准备 namespace、Secret 和远端域名解析 |
| `stage-runtime-images.py` | 通过原生 `k3s ctr` 预置固定 digest 镜像，包括 migration 的 PostgreSQL 客户端 |
| `configure-prs.py` | 配置 DPS PRS 与 PowerSteering 开关、三库严格 TLS、内部 S3、LDAP DPS 凭据 Secret 和所需持久卷 |
| `stage-prs-images.py` | 根据 `config/prs/runtime-images.json` 将固定 PRS/PowerSteering 与 SeaweedFS 镜像预置到原生 K3s |
| `install-dps.sh` | 校验保存的 chart、原生节点和外部数据库范围后执行显式 Helm upgrade --install |
| `register-devices.sh` | 缺少时注册 GB300 33kW、0.95 效率电源架设备；存在且一致时不写，配置不同则拒绝覆盖 |
| `import-topology.sh` | 注册设备、校验、首次导入 DPS 0.9 拓扑并核验 72 条 Agent 关联；保留 inactive，同名拓扑拒绝重复导入 |
| `update-topology.sh` | 使用官方 API 与当前 hash 校验更新并回读 72 条关联；关联已一致时跳过写入，不用 force，不激活拓扑 |

以下仅为现有安装的维护/历史迁移流程；首次安装使用上方新入口。已有环境的 LDAP 接入顺序为 prepare-ldap.py → ldap-start.sh → ldap-status.sh → configure-ldap-auth.py。准备 PRS 时继续执行 prepare-prs-databases.py → configure-prs.py → prepare-namespace.sh → stage-runtime-images.py → stage-prs-images.py → install-dps.sh → dps-login.sh。运行时全局 PRS 开关的实际设置记录在根目录 installstep.md。常规流程复用保存的固定 LDAP 运行镜像；build-ldap.sh 是可选重建入口。OpenLDAP 与 PostgreSQL 独立于 DPS Helm release，只读 bind 账号与 UI 用户分开。

PRS 配置已启用 DPS PRS 和 PowerSteering 2.1.0，使用三个独立数据库与内部 SeaweedFS 4.18 S3。拓扑保持 inactive，当前无资源组和 PRS domain；组件部署与接口检查不代表动态功率控制已经验证。

安装入口已执行成功；重复 `install-dps.sh` 会执行 Helm upgrade，日常查看状态不需运行该脚本。首次导入和更新均读取 `config/topology-4rack-dps09.json`，不会读取验证报告、重置拓扑或赋予功率策略。

```bash
cd /raid/vince/deploy
source dps-install/config/dps-env.sh
kubectl --context dps-l20-12 -n dps get pods,pvc
helm --kube-context dps-l20-12 -n dps list
dpsctl server-version
dpsctl agent list
dpsctl topology list
```

项目环境导出 `DPS_KUBE_CONTEXT=dps-l20-12`、`DPS_KUBE_NODE=l20-12`，
并固定 dpsctl 的 CA、凭据和日志路径。旧容器节点创建入口与工具已退出交付目录，仅在迁移归档中保留。

安装与维护脚本不自动调用 `verification/scripts/`。配置准备脚本不单独安装 DPS；现有手动安装入口为 `install-dps.sh`，新实例入口 `install-from-zero.sh` 也执行明确的 Helm 安装。所有脚本均不调用 SDK 部署入口。

`kubernetes.sh stop` 只执行 `systemctl stop k3s`，现有 Pod/containerd 任务可能继续运行，不能将其当作停止全部 DPS 工作负载或功率控制的保证。凭据、kubeconfig 和私钥仅保存到权限 600 的专用文件，不输出到普通日志。

