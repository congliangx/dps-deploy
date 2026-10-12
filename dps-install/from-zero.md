# 从零部署 DPS 0.9 与四个 GB300 rack 模拟器

本页用于在新的 Ubuntu 22.04/24.04 amd64、systemd 主机上，从仓库源码准备并部署一个新实例。公开入口为 install-from-zero.sh；默认项目根目录是脚本所在仓库，使用 --root 可指定另一份同内容仓库。现有 L20-12 环境的维护见 [访问说明](dps-access.md)、[前置维护](prerequisites.md) 和 [实际记录](../installstep.md)。

入口获取固定版本的 chart/镜像及 LDAP 构建包，生成本实例的密码、CA/证书、JWT、配置与 13 份 Kubernetes Secret 输入，安装物理机原生 K3s，启动独立 BMC/PostgreSQL/OpenLDAP，再通过 Helm 部署 DPS/PRS。SDK 不安装 DPS。默认导入四个 rack、72 个计算节点、288 GPU、144 CPU，拓扑保持 inactive，PRS 全局开关设为 true；不创建资源组或写 BMC 功率。

## 主机准备

需要 root 权限、可用的主机 IPv4 和对应物理网卡、systemd，以及安装包/镜像来源的网络访问。shell 入口准备 Docker/Compose v2、Python YAML、OpenSSL 等所需系统软件；系统包不提交到 Git。已有 Docker 会复用；若其没有 Compose v2，需要安装与已有 Docker 匹配的 Compose 后继续。download-only/prepare-only 仍会检查或准备这些主机依赖。固定版本的 K3s、Helm、kubectl、dpsctl 与应用镜像按项目脚本/manifest 获取。

主机必须能访问 NVIDIA NGC Helm/nvcr.io、Docker Hub、Debian snapshot、Ubuntu 软件源及工具下载源。当前固定资源已验证可获取；如果所在环境要求 NGC 权限，安全提供 NGC_API_KEY 或完成 Docker registry 登录，不在命令历史、配置示例或 Git 中保存密钥。

为新实例选择未占用的 API/UI 域名、PostgreSQL/LDAP 端口、连续 72 个 BMC 端口和独立 Docker 子网。参数不应与正在运行的部署冲突。已被其他 namespace/release 的 Ingress/Traefik 路由占用的 API/UI 域名会在启动应用服务前被拒绝。现有非 bootstrap 身份或不匹配的文件/缓存会被拒绝，不能通过删除已有身份或持久数据来绕过。

## 首次部署

先克隆仓库并替换示例中的主机参数：

~~~bash
git clone https://gitlab-master.nvidia.com/congliangx/dps-deploy.git
cd dps-deploy
sudo bash dps-install/scripts/install-from-zero.sh \
  --host-ip YOUR_HOST_IPV4 \
  --host-name YOUR_HOST_NAME \
  --interface YOUR_INTERFACE
~~~

host-ip 是必填 IPv4，host-name 与 interface 应对应目标主机。以上为全新主机默认实例；namespace/release/instance-prefix 均为 dps，PostgreSQL 端口 15432、LDAPS 1636、BMC 18443–18514，PG 子网 172.30.90.0/24，API/UI 域名 api.dps.lab 与 ui.dps.lab。

公开的 [bootstrap 配置示例](config/bootstrap.example.yaml) 只描述部署参数，不保存密码或 TLS 身份。示例 host_ip 为 null，host_name 为 dps-lab、interface 为 bond0；需按实际主机修改。命令行参数覆盖同名配置字段。可以审阅后通过 --config 指定它，并按入口实际参数覆盖目标主机设置：

~~~bash
sudo bash dps-install/scripts/install-from-zero.sh \
  --config dps-install/config/bootstrap.example.yaml \
  --host-ip YOUR_HOST_IPV4 \
  --host-name YOUR_HOST_NAME \
  --interface YOUR_INTERFACE
~~~

| 参数 | 用途 / 默认值 |
|---|---|
| --root PATH | 同内容仓库的绝对根目录；默认脚本所在仓库 |
| --host-ip IPv4 | 必填，宿主机管理 IPv4 |
| --host-name NAME、--interface IFACE | 目标物理主机名与接口 |
| --namespace NAME、--release NAME | Kubernetes namespace / Helm release，默认 dps |
| --agent-id ID | Agent 路由标识，默认 gb300-lab-agent |
| --instance-prefix PREFIX | 独立 Docker 容器等实例名称前缀，默认 dps |
| --api-name NAME、--ui-name NAME | 默认 api.dps.lab / ui.dps.lab |
| --pg-port PORT、--ldap-port PORT | 默认 15432 / 1636 |
| --bmc-start-port PORT | 72 个连续 HTTPS 端口的起点，默认 18443 |
| --pg-subnet CIDR | 默认 172.30.90.0/24，需与现有网络分开 |
| --config FILE | 读取公开部署参数配置 |
| --download-only | 只获取固定资源与构建 LDAP 运行镜像，不部署应用 |
| --prepare-only | 下载并生成本实例安装输入，不部署应用 |
| --kubeconfig FILE | 显式复用本机已有物理机原生 K3s；不创建容器模拟节点 |

独立资源获取入口还支持：

~~~bash
python3 dps-install/scripts/download-artifacts.py --component all
# 仅使用现成 chart 作为经过 SHA256/版本验证的缓存输入
python3 dps-install/scripts/download-artifacts.py \
  --component chart --chart-file /path/to/dps-0.9.0.tgz
~~~

没有现成 chart 时，默认从官方 NGC 下载。匹配缓存保留，不匹配缓存拒绝覆盖。LDAP 从固定 Debian digest 与 17 个固定 SHA256 的 deb 构建，生成本次新镜像 ID/归档，使用 dps-openldap:2.6.10-bootstrap；不依赖 L20-12 原始 tar 的 hash 或旧镜像 ID。

## 安装过程与生成文件

1. 获取 DPS 0.9.0 chart、11 个固定镜像 digest、LDAP 构建配方所需 deb；LDAP 构建产物记录在 config/ldap/runtime-build.json。
2. 新建 BMC、独立 PostgreSQL 和 OpenLDAP 的配置、随机密码、可信 TLS，以及 DPS/Agent/UI、LDAP、PRS 所需 Secret；准备四个 PRS/Core 数据库与外部连接。
3. 安装原生 K3s 和匹配工具，或按显式 kubeconfig 复用现有原生集群；等待 Traefik/Ingress CRD 就绪，核对 namespace 与域名归属，将固定镜像导入该运行时。
4. 启动独立 Docker BMC/PG/LDAP 服务，应用 Secret，并用明确 namespace/release 的 Helm 命令安装 DPS/PowerSteering 2.1.0 与 SeaweedFS 4.18。
5. 使用本实例真实 LDAP 用户登录，注册 33kW 电源架、导入四个 rack 的 inactive 拓扑并核验 Agent 关联，设置并读回 prs_enabled=true。

私密输入、下载包、构建归档和运行数据均留在所选 root 下，并由 Git 排除。重点位置：

| 路径（相对项目 root） | 用途 |
|---|---|
| dps-install/config/bootstrap-settings.json | 本实例参数、root 归属与安装状态，权限 600 |
| dps-install/config/dps-env.sh | 本实例 kubectl/Helm/dpsctl 环境 |
| dps-install/config/values.yaml | 本次生成的 Helm 安装输入 |
| dps-install/config/dps-access.json | 真实 LDAP UI/CLI 用户凭据 |
| dps-install/config/bmc-endpoints.csv、bmc-credentials.json | 72 个 BMC 地址与模拟凭据 |
| dps-install/config/postgresql-credentials.json | 独立数据库凭据 |
| dps-install/config/ldap/ | 目录配置、凭据、TLS 和本次运行镜像元数据 |
| dps-install/config/tls/ca.crt | 新实例 DPS 公共 CA，供客户端信任 |
| dps-install/config/kubernetes/kubeconfig.yaml | 项目集群访问配置 |
| dps-install/data/ | 数据库、目录及首次自建 K3s 数据与备份 |
| hardware-sim/runtime/ | 本实例模拟器 Compose、路由和 TLS |

### 密码、证书与 Secret 的生成方式

可以先执行同样参数并加 --prepare-only，审阅本实例生成输入，再用相同参数执行完整安装。密码通过 Python secrets 随机生成，证书通过 OpenSSL 新建 CA 和包含目标 IP/域名 SAN 的服务器/客户端证书，JWT 使用新的 RSA 私钥。Secret 输入由这些受限文件生成，不需要复制现有 Secret 或手工填写固定密码。

| 生成入口 | 生成身份与外部 Secret |
|---|---|
| prepare-bmc-fresh.py | BMC CA/HTTPS 证书、模拟用户名/随机密码；bmc-shared-secret、dps-bmc-ca |
| prepare-postgresql.py | PG CA/服务端证书、postgres 与 dps 随机密码；dps-postgresql、dps-postgresql-ca |
| prepare-ldap-fresh.py | LDAP 用户/只读 bind/管理密码、CA 与服务端/client 证书；dps-ldap-bind、dps-ldap-ca、dps-ldap-client-tls |
| prepare-dps-fresh.py | DPS/Agent/Ingress 证书、JWT、S3 随机凭据；dps-server-tls、dps-agent-tls、dps-ingress-tls、dps-jwt-keys、dps-prs-s3、dps-prs-dps-auth |

完整入口负责这些脚本的参数和依赖顺序，随后将 13 份 Secret 应用到所选 namespace。已有实例缺失 JWT、证书/私钥或 S3/BMC 凭据时停止，需恢复该实例的缺失私密输入；已有 Secret 输入与身份不同也会拒绝覆盖。不能用再次安装来隐式更换身份。缺失的派生 Secret 文件可从完整且一致的原身份重新生成。

BMC 对外 72 个 HTTPS URL 使用 nginx 上本实例 CA 签发的证书，DPS/客户端严格校验；mock 后端的 ssl/--ssl 自行生成私有证书，Docker 内部代理使用 proxy_ssl_verify off，后端不挂载项目证书/私钥，BMC CA 签发私钥不挂载到任何容器。模拟器 fixture/认证与真实硬件的区别见 [硬件模拟说明](../hardware-sim/bmc-access.md)。

密码、Secret、私钥、JWT 和 kubeconfig 文件权限为 600，私密目录为 700。克隆源码不会复制旧 LDAP 用户密码、JWT 签名密钥、CA 或数据库数据；入口生成的是一个新实例。已有 bootstrap 输入仅在参数与文件一致时复用；普通旧安装/认证迁移状态不会被当作可覆盖的冷启动身份。

## 复用现有原生 K3s

在同一物理机做隔离新实例时，仍须选择另一份 root、namespace/release/prefix、域名、空闲端口和子网，并显式传入 --kubeconfig。该方式复用本机原生集群，保留其现有持久化路径；PVC 的实际存储位置以该集群配置和验收记录为准。它不证明裸机 OS/K3s 首次安装链已经在该轮测试中执行。

~~~bash
sudo bash dps-install/scripts/install-from-zero.sh \
  --root /path/to/fresh-repo \
  --host-ip YOUR_HOST_IPV4 --host-name YOUR_HOST_NAME --interface YOUR_INTERFACE \
  --namespace dps-cold --release dps-cold --instance-prefix dps-cold \
  --api-name api.cold.dps.lab --ui-name ui.cold.dps.lab \
  --pg-port 25432 --ldap-port 2636 --bmc-start-port 19443 \
  --pg-subnet 172.30.91.0/24 \
  --kubeconfig /path/to/existing-native-k3s.yaml
~~~

上述端口/子网仅为需核对的示例，不能假定目标主机上可用。不要对现有 /raid/vince/deploy 的运行部署直接执行新实例初始化。

## 完成后访问与核对

~~~bash
cd /path/to/this-repo
source dps-install/config/dps-env.sh
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get pods,pvc
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" list
dpsctl server-version
dpsctl agent list
dpsctl topology list
~~~

环境中的 DPS_NAMESPACE 是本次选择的 namespace。客户端将本次 API/UI 域名解析到 host-ip，信任本次 config/tls/ca.crt，再使用本次 config/dps-access.json 中的 LDAP 账号登录。L20-12 原部署的密码和 CA 不属于这个新实例。

2026-10-12T10:25:25.389759+08:00 的完整隔离新实例验收为 44/44：namespace/release 为 dps-cold-test，独立 Docker 为 BMC 后端、代理、PG、LDAP 四个容器；DPS/PRS/S3 九个工作负载 Ready、0 restart，三个 S3 PVC Bound。新密码/CA/JWT/13 份 Secret、四 rack/72 BMC 严格 CA 与 288 GPU/144 CPU、CLI/UI LDAP 正负登录、Controller 实际 LDAP/DPS TLS、两个 PRS Pod 的 PG verify-full、S3 签名读写/匿名拒绝、原始 API 回读 72 条 AgentId 及 inactive/no power writes 均已检查。UI 使用 HTTPS 会话/代理 API 验证，未进行浏览器视觉验收。

本轮从空仓库部署一个新实例，显式复用现有物理机原生 K3s，没有执行完整裸机 OS/K3s 首次安装；该范围不能扩大为新 OS 安装或真实 GB300 硬件验收。独立 PG 新建链 33/33、LDAP 新建链 24/24，以及固定资源网络获取/缓存保护/LDAP 无网络构建分项也已通过。公开摘要见 [from-zero-summary.json](../verification/reports/from-zero-summary.json)；完整报告保留在远端 verification/archive/cold-bootstrap/fullstack/repo/verification/reports/cold-bootstrap-fullstack.json。2026-10-12T10:28:56.572559+08:00 的完整入口重入退出 0：46 份证书/密钥/凭据/Secret 内容不变，数据库 sentinel 保留并在检查后清理；结果记录在同一 fullstack/repo/verification/reports 下的 cold-bootstrap-rerun.json。该检查验证本轮新实例的身份与数据保留。

拓扑默认 inactive，Agent connected 或 Pod 到 BMC 的可信 HTTPS GET 不代表 Core→Agent→BMC 派发或动态功率控制已经通过。拓扑激活、资源组和功率写入属于后续明确操作，首次安装不自动执行。

## 与现有维护流程的区别

首次部署使用本页入口。已有 L20-12 服务继续按 [维护脚本](scripts/README.md) 与 [访问说明](dps-access.md) 维护；原 LDAP alwaysAllow→LDAP/JWT 轮换属于历史迁移，新实例直接建立真实 LDAP，不需要重放旧迁移或恢复旧 tar。旧版本 368f921 的缺失输入审计保留为历史，不代表本次新增下载与生产配置链的能力。
