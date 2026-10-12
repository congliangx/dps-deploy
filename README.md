# DPS 0.9 安装与基础设施选择

本仓库交付 DPS 0.9 的手工 Helm 安装说明，以及没有现成基础设施时可选的 Kubernetes、PostgreSQL、OpenLDAP 和 GB300 BMC 模拟器部署步骤。客户按已有环境选择组件；真实 GB300 BMC 可以直接接入 DPS，只有缺少硬件的 Lab 才需要模拟器。SDK 只用于硬件模拟，安装 DPS 不依赖 SDK。

安装前先读 [前置要求与手工安装](dps-install/manual-prerequisites.md)：同一页先列准备项和新建/复用选择，再给出版本说明、具体安装命令与状态检查。固定版本及完整 Lab 检查单只描述本仓库实验环境，客户可以复用满足要求的现有服务。

## 安装内容与组件选择

先填写自己的环境清单，再选择下面需要新装的部分。已有服务应对接其地址、访问权限和证书，无需为使用本仓库再部署一套。

| 部分 | 已有环境如何处理 | 没有时如何选择 |
| --- | --- | --- |
| DPS Core / Agent / UI | Core 是本体；管理硬件时部署 Agent，UI 按需；维护现有 DPS 时复用其身份、数据与 release | 按 [DPS 手工安装](dps-install/manual-install.md) 准备应用 values、Secret 并使用 Helm |
| Kubernetes | 使用已有 kubeconfig/context、namespace、StorageClass 和网络；跳过主机 K3s 初始化 | 本仓库提供 [单物理机原生 K3s Lab 步骤](dps-install/manual-prerequisites.md)，客户可使用自己的集群方案 |
| GB300 BMC | 直接提供真实 Redfish URL、账号/密码、受信 CA 和符合实际硬件的拓扑；不安装模拟器 | 缺少硬件时可选 [4 rack BMC 模拟器](hardware-sim/README.md)，生成 72 个模拟入口 |
| PostgreSQL | 复用数据库服务，准备 DPS 所需数据库、角色权限与 TLS；将连接参数和凭据 Secret 对接 DPS | 可选 [独立 PostgreSQL Lab 部署](dps-install/manual-postgresql.md)；按是否启用 PRS 准备相应数据库 |
| LDAP / 身份服务 | LDAP 模式下复用现有目录，配置 URL、bind 身份、用户/组映射及 TLS；不创建 Lab 用户或目录 | 需要本地用户名/密码验证时可选 [独立 OpenLDAP](dps-install/manual-ldap.md)；其他身份模式需使用 DPS 0.9 实际支持的配置 |
| PKI、域名与 Ingress | 复用受信 CA、已签发证书、现有 DNS 和 Ingress controller；核对 SAN、访问域名、证书链和 Secret 引用 | Lab 手册提供证书生成与 Traefik 接入示例；客户可以按自己的 PKI / Ingress 方案配置 |
| 持久存储 | 选择已有 StorageClass、容量、访问模式和备份策略，不要求使用 Lab 的 local-path | Lab 的本地持久卷仅用于单节点验证；生产存储按客户要求提供 |
| PRS / S3 | PRS 按需求启用；使用时对接其数据库和对象存储及访问 Secret | 本仓库完整 Lab 开启 PRS 并部署 SeaweedFS；不需要 PRS 时不应照搬该可选组件配置 |

**已有基础设施仍需准备 DPS 的应用配置和 Kubernetes Secret。** 外部数据库、LDAP 或 BMC 的密码与受信 CA 不会因服务已经存在而自动出现在 DPS namespace 中。应按所选功能创建或引用正确的 Secret；证书可复用客户 PKI，账号密码可由现有服务管理员提供，不必重新生成。具体字段、Secret 键名与手工对接步骤见 [已有基础设施对接指南](dps-install/existing-infrastructure.md)。

## 已有服务时仍需哪些 Secret

服务可以复用，DPS 所在 namespace 仍需按实际功能准备可引用的凭据和信任材料。已有匹配 Secret 可以直接使用，或由客户的秘密/证书控制器供给；无需为对接而更改已有服务密码或 CA。

| 选择 | 需要供给 DPS 的材料 |
| --- | --- |
| 外部 PostgreSQL | 真实应用账号密码 Secret；TLS CA 挂载按信任方式配置。Core 库及 PRS 可选三库/权限仍需准备 |
| 真实 BMC | 实机账号 JSON 或所选 token Secret；按拓扑分别引用，私有信任链按需挂载 |
| 现有 LDAP | 只读 bind 密码、CA 和本页 Core LDAP 配置所需 client cert/key；按目录 schema 配置用户/组授权 |
| DPS Core / Agent | 服务端 TLS、Agent mTLS 身份；缺少时创建，已有 PKI 材料可复用 |
| API / UI 入口 | 所选 HTTPS 路由需要的证书 Secret；终止 TLS 的 controller 后端信任按其机制配置 |
| LDAP 签发 DPS token | 持久 JWT RSA key：引用已有 Secret，或使用 chart 首次生成并保留的方式 |
| 启用 PRS | S3 bucket 的真实 access/secret key；Controller 登录 DPS 的用户凭据，区别于 LDAP bind 账号 |
| 私有镜像仓库 | 客户已有或新建的 image pull Secret，配置到实际启用组件 |

**当前 Lab 的 13 个外部 Secret 不是所有客户必须创建的固定清单。** 认证模式、PKI、Ingress、PRS/S3 等选择改变所需 Secret；改名/合并后须更新 values 的 namespace、名称、key 和挂载路径。逐项原生创建命令、现有 Secret 复用规则及可渲染示例见 [对接已有基础设施](dps-install/existing-infrastructure.md)。客户 PG/LDAP/BMC/S3 的凭据使用实际服务签发值；只有缺少的 DPS 自身证书或 JWT 身份才按需新建。

## 三种常见安装路径

1. **已有 Kubernetes、PostgreSQL、LDAP 和真实 BMC。** 从 [已有基础设施对接指南](dps-install/existing-infrastructure.md) 开始，跳过 K3s、数据库、目录服务和模拟器安装。确认所需数据库/权限，准备目标 namespace 内的 Secret，填写客户自己的 DPS values，审阅 Helm 渲染结果后安装 DPS，最后按实际启用的组件验证。
2. **已有 Kubernetes 和真实 BMC，缺少数据库或身份服务。** 保留已有集群与 BMC，只选择缺少部分的 [PostgreSQL](dps-install/manual-postgresql.md) / [OpenLDAP](dps-install/manual-ldap.md) 手工步骤；再按 [对接指南](dps-install/existing-infrastructure.md) 汇总连接参数和 Secret，并安装 DPS。可以只新装其中一个服务。
3. **没有硬件和基础设施的完整 Lab。** 按 [installstep.md](installstep.md) 的顺序部署原生 K3s、4 rack 模拟器、独立 PostgreSQL/OpenLDAP、DPS 和可选 PRS，再使用 [验证说明](verification/README.md)。这条路径复现本仓库当前验证环境。

[install-from-zero](dps-install/from-zero.md) 是完整 Lab 的便捷自动化，具有其现有环境检查与复用边界；它不是按客户任意现成基础设施自由选择组件的安装器。已有企业环境应使用手工对接、Secret 与 Helm 流程，不要通过改一项地址后直接执行全套 Lab 脚本。

[installstep.md](installstep.md) 只包含可重复安装步骤。完整历史实录、失败修复与带日期验收位于 [docs/operation-history.md](docs/operation-history.md)，不能把其中一次性迁移命令当成当前安装流程。

## Lab 统一参数与 DPS 应用配置

根 [deployment.yaml](deployment.yaml) 统一设置本仓库 Lab 安装/维护/验证脚本的主机/IP/网卡、namespace/release、域名/AgentId、端口/子网、固定版本及 Compose project。它不是 DPS Helm values，也不能完整描述任意客户的远端数据库、LDAP schema、Ingress 或存储方案。

复用客户基础设施时，DPS 的实际连接参数、认证模式、TLS/Secret 引用、Ingress、StorageClass 和可选 PRS 配置应写入用户自己的 Helm values；目标集群通过用户自己的 kubeconfig/context 选择。公开 [values.example.yaml](dps-install/config/values.example.yaml) 是当前 Lab 的参考配置，不能只替换 host_ip 后直接套用；详细修改项见 [对接指南](dps-install/existing-infrastructure.md)。生成配置和私密输入仍放在用户选择的 runtime_root，以下目录表描述仓库 Lab 的组织方式。

| 逻辑位置 | 内容 |
| --- | --- |
| SOURCE_ROOT | Git 仓库根：公开模板、固定包来源/SHA/digest、文档、安装/维护/验证脚本 |
| RUNTIME_ROOT | deployment.yaml 的 runtime_root：下载包、生成配置/证书/密码/Secret、数据、systemd 副本、日志/报告/archive |
| RUNTIME_ROOT/hardware-sim/runtime | 独立 BMC config、nodes、nginx、Compose、TLS |
| RUNTIME_ROOT/dps-install/config | values、拓扑、PG/LDAP/TLS/PRS 输入、kubeconfig 与私密访问凭据 |
| RUNTIME_ROOT/dps-install/data | 独立数据库、K3s/containerd/kubelet/local-path、备份 |
| RUNTIME_ROOT/verification | 可复验结果、日志、历史和临时材料 |

SOURCE_ROOT 从脚本或当前 Git 工作区推导；RUNTIME_ROOT 由用户选择，允许与源码同根、位于源码子目录、源码外部或其上级目录。runtime_root 可以使用绝对路径，也可以使用相对 deployment.yaml 所在目录的路径：

| runtime_root 示例 | 布局 |
| --- | --- |
| .runtime | 仓库内的专用运行子目录 |
| . | 源码与运行材料同根；公开模板与生成配置分别使用不同文件 |
| /srv/dps-lab | 自选绝对运行目录 |

Git 只跟踪公开源码，生成物在任何布局下都不应提交。可选命令参数 --runtime-root 的相对路径按命令执行目录解析。

L20-12 当前采用 SOURCE_ROOT=/raid/vince/deploy、RUNTIME_ROOT=/raid/vince/deployed-test，以保持该仓库工作目录干净。这是当前实例的布局，其他用户可选择自己的目录。修改配置不会自动搬迁已有实例；本次文档调整继续使用当前目录与数据。

系统软件按机制使用 /usr/local/bin 与 /etc/systemd，副本/缓存/数据在 RUNTIME_ROOT；不用 k3d/kind 节点容器。

~~~bash
ssh root@L20-12
cd /raid/vince/deploy
# 使用 root Bash；python3-yaml 是配置解析器所需的 OS 包。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

请先进入实际 clone 的仓库根目录；上述 cd 仅为 L20-12 示例。其他手册从当前 Git 仓库推导源码根，不需逐份改路径。

## 完整 Lab 的手工安装顺序

1. [主机、固定 artifact 下载、原生 K3s](dps-install/manual-prerequisites.md)：curl/SHA、docker pull/build、物理节点与 containerd 镜像。
2. [硬件模拟](hardware-sim/README.md)：72 URL、随机 BMC 密码、新 CA、nginx/Compose 与只读 Redfish 检查。
3. [独立 PostgreSQL](dps-install/manual-postgresql.md)：TLS/SCRAM、非 superuser dps、Core/PRS 四库、持久化与备份。
4. [独立 OpenLDAP](dps-install/manual-ldap.md)：用户/组/只读 bind、LDAPS、客户端 TLS 与备份。
5. [DPS / PRS](dps-install/README.md)：当前 Lab 的 13 Secrets、values、Helm、真实 LDAP 登录、电源类型、4 rack inactive 拓扑与 PRS=true；客户启用不同组件时所需 Secret 和工作负载数量不同。
6. [独立验证](verification/README.md)：安装输入与验证脚本/结果分开，健康 GET 与动态功率控制分开。

每个组件都有完整原生命令、说明和预期结果；仓库自编安装脚本不作为手工步骤的前置黑盒。可选脚本索引在 [scripts/README.md](dps-install/scripts/README.md)。[from-zero.md](dps-install/from-zero.md) 说明首次实例与维护的区别。

## 已验证范围与现有实例

L20-12 为实际单节点 Kubernetes；DPS 0.9.0、Power Steering 2.1.0、SeaweedFS 4.18、独立 PG 17.11/OpenLDAP 2.6.10。DPS 使用真实 LDAP 用户 dps-lab、组映射 admin，OIDC 关闭。API https://api.dps.lab、UI https://ui.dps.lab，客户端须解析到配置中的 host_ip 并信任 runtime/dps-install/config/tls/ca.crt。

2026-10-12 空源码副本的新身份/新数据隔离全栈验收 44/44，通过复用现有物理 K3s；PG 独立 33/33、LDAP 独立 24/24；完整重入 46 份证书/密钥/凭据/Secret 内容及数据库保留。该轮没有另一台空白 OS/K3s 首装验收。精简/详细证据在 runtime/verification；日期与完整操作见历史记录。

4 rack / 72 节点 / 288 GPU / 144 CPU 是模拟硬件。拓扑默认并保持 inactive；PRS 部署开启、尚无活跃 ResourceGroup/domain。BMC/Agent 网络严格 TLS GET 成功不代表 Core→Agent 健康派发或动态功率控制已验证。模拟器不强制认证，fixture 固定型号/UUID 的限制见 [BMC 访问说明](hardware-sim/bmc-access.md)。

2026-10-12 已保留原身份/数据完成 runtime 迁移：9 工作负载 Ready、4 PVC Bound；12:11 的全栈 43/43、PRS 35/35 与身份/路径 11/11 通过。报告在 /raid/vince/deployed-test/verification/reports，本次实录追加在 operation-history。

## Git 与私密输入

Git 保留必需脚本、公开拓扑/values 模板、deployment.yaml、固定下载清单与 LDAP 构建配方；网络下载包、SDK/vendor、运行数据、密码/Secret、证书/私钥/kubeconfig、日志/报告/archive 均留 RUNTIME_ROOT。仓库内的专用运行子目录由 .gitignore 排除；报告是验收证据，不是安装依赖。

新建完整 Lab 按手工步骤生成新身份与空数据；复用客户服务时只准备 DPS 需要的授权、证书和 Secret，不初始化或覆盖其已有数据库/LDAP。维护已有 DPS 实例时使用其保存的身份、values 和数据，不重建 CA/JWT/账号或重播历史迁移。当前跟踪范围以根 [.gitignore](.gitignore) 为准。
