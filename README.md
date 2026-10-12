# DPS 0.9 安装与基础设施选择

本仓库提供 DPS 0.9 Helm 安装说明，以及完整 Lab 和独立组件的脚本入口。按现有环境选择安装范围：真实 BMC 直接接入；缺少硬件时才部署 GB300 模拟器。SDK 只用于模拟 BMC。

## 安装完成后：访问与日常维护

**安装后请按 [dps-access.md](dps-install/dps-access.md) 访问和维护 Kubernetes / DPS。**

每次新开 SSH/Bash 会话，先加载环境，再查询 Kubernetes/Helm 或登录 DPS CLI。文档也说明浏览器域名与 CA 配置、凭据文件位置、状态检查、日志、备份和服务启停。维护使用已有身份与数据。

## 先选择需要安装的组件

安装前阅读 [前置要求](dps-install/manual-prerequisites.md)。已有服务保留原配置，只准备 DPS 所需连接参数、权限和信任材料。

| 组件 | 已有时 | 缺少时 |
| --- | --- | --- |
| Kubernetes | 使用目标 kubeconfig/context、namespace、StorageClass 和网络 | [物理机原生 K3s Lab](dps-install/manual-prerequisites.md)，或客户自选集群方案 |
| BMC | 对接真实 Redfish URL、账号、CA 和实际拓扑 | 可选 [4 rack / 72 节点模拟器](hardware-sim/README.md) |
| PostgreSQL | 准备 Core 数据库、应用角色和 TLS；启用 PRS 时增加其数据库 | [独立 PostgreSQL](dps-install/manual-postgresql.md) |
| LDAP / 身份服务 | LDAP 模式对接目录、bind 身份、用户/组映射和 TLS | [独立 OpenLDAP](dps-install/manual-ldap.md)，用于真实用户名/密码验证 |
| PKI、DNS、Ingress | 使用已有证书、域名和 controller，核对 SAN 与信任链 | Lab 手册提供 CA/证书及 Traefik 示例 |
| 持久存储 | 使用满足容量、访问模式和备份要求的 StorageClass | Lab 使用单节点 local-path |
| PRS / S3 | 按需启用 PRS，并对接其数据库、对象存储和访问凭据 | 完整 Lab 开启 PRS，使用 SeaweedFS |
| DPS Core / Agent / UI | 维护已有 release 时保留身份和数据 | 按 [DPS 手册](dps-install/manual-install.md) 或 [已有环境对接](dps-install/existing-infrastructure.md) 安装 |

**复用服务仍需配置目标 namespace 中的 Secret。** 数据库、LDAP、BMC、S3 的真实凭据和私有 CA 由已有服务提供；DPS 自身 TLS/mTLS、JWT、Ingress 证书及镜像拉取凭据按所选功能生成或复用。已有 Secret 或秘密/证书控制器也可使用，但 values 的名称、键和挂载必须匹配。Lab 的 13 个 Secret 不是客户通用清单，逐项命令见 [已有基础设施对接](dps-install/existing-infrastructure.md)。

## 选择安装路线

1. **已有基础设施和真实 BMC：** 从 [对接指南](dps-install/existing-infrastructure.md) 准备自己的 Helm values、Secret 和访问权限，审阅渲染结果后安装 DPS。
2. **只缺少部分组件：** 用下方独立脚本或对应手册新建缺少的服务，再按对接指南安装 DPS。
3. **从零搭建完整 Lab：** 按 [installstep.md](installstep.md) 选择完整脚本、分阶段脚本或逐步手工安装。

同一组件的脚本与手工安装二选一；安装完成后只执行检查，不重复生成身份或启动服务。完整 Lab 脚本固定部署模拟器、独立 PG/LDAP、原生 K3s、DPS 和 PRS；客户按需组合使用组件入口与对接指南。

### 完整 Lab：一条脚本

先在部署主机使用 root Bash，进入实际 clone 的仓库根目录，修改 [deployment.yaml](deployment.yaml)：

~~~bash
bash dps-install/scripts/install-from-zero.sh --config deployment.yaml
~~~

分阶段准备、显式复用本机原生 K3s、仅安装 DPS 的条件见 [installstep.md](installstep.md)；脚本验证范围见 [from-zero.md](dps-install/from-zero.md)。这些入口不能通过只改地址来接管任意客户基础设施。

### 独立组件：只执行需要的一项

先完成 [installstep.md 第 0–1 节](installstep.md) 的主机依赖与参数设置，在源码根选择：

| 组件 | 一键安装命令 | 动作、产物与手工替代 |
| --- | --- | --- |
| BMC 模拟器 | bash hardware-sim/scripts/install-bmc.sh --config deployment.yaml | [BMC 手册](hardware-sim/manual-install.md) |
| PostgreSQL | bash dps-install/scripts/install-postgresql.sh --config deployment.yaml | [PG 手册](dps-install/manual-postgresql.md) |
| OpenLDAP | bash dps-install/scripts/install-ldap.sh --config deployment.yaml | [LDAP 手册](dps-install/manual-ldap.md) |

入口下载/构建并启动自身组件，生成密码、证书、配置和 Secret YAML；Secret 只落盘，后续 DPS 安装时应用。脚本管理的同一实例可保留身份重入；手工或历史实例使用原配置维护。独立组件已启动后，按 DPS 手册/对接指南继续，不再接续整套 install-from-zero 初始化。

### 逐步手工安装

[主机/K3s](dps-install/manual-prerequisites.md) → [可选 BMC](hardware-sim/manual-install.md) → [可选 PG](dps-install/manual-postgresql.md) → [可选 LDAP](dps-install/manual-ldap.md) → [DPS / PRS](dps-install/manual-install.md) → [按安装范围验证](verification/README.md)。

各 manual 保留完整原生命令，并说明脚本阶段和生成物。[脚本索引](dps-install/scripts/README.md) 提供安装与维护入口。

## 配置与目录

[deployment.yaml](deployment.yaml) 统一设置 Lab 脚本的主机、IP、namespace/release、域名、端口、版本及 Compose project。客户实际的数据库/LDAP/Ingress/存储和认证配置写入自己的 Helm values，目标集群由 kubeconfig/context 选择。[values.example.yaml](dps-install/config/values.example.yaml) 是 Lab 参考，修改项见对接指南。

| 位置 | 内容 |
| --- | --- |
| SOURCE_ROOT | Git 源码、公开模板、固定包来源/SHA/digest、文档和脚本 |
| RUNTIME_ROOT/hardware-sim/runtime | 生成的模拟器、nodes、nginx、Compose 与 TLS |
| RUNTIME_ROOT/dps-install/config | values、拓扑、PG/LDAP/Secret/TLS、kubeconfig 与访问凭据 |
| RUNTIME_ROOT/dps-install/packages、data | 下载/构建产物；数据库、K3s、持久卷与备份 |
| RUNTIME_ROOT/verification | 日志、报告、archive 和临时材料 |

SOURCE_ROOT 从脚本位置推导。runtime_root 由用户选择，可以同根、位于源码子目录、源码外部或上级目录；例如 .、.runtime、/srv/dps-lab。配置中的相对路径按 deployment.yaml 所在目录解析，CLI --runtime-root 的相对路径按命令执行目录解析。

本仓库 Lab 安装后，在源码根加载环境：

~~~bash
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

后续登录与访问按顶部的 dps-access.md。系统软件仍使用标准二进制/systemd 路径，运行副本和数据写入 runtime；修改目录设置不会自动搬迁已有实例。

## 当前 L20-12 实例与验证范围

当前源码为 /raid/vince/deploy，运行材料为 /raid/vince/deployed-test；这组目录只描述本实例。原生单节点 K3s 上运行 DPS 0.9、真实 LDAP 和 PRS；4 rack / 72 节点 / 288 GPU / 144 CPU 来自模拟器。

拓扑保持 inactive，无活跃 ResourceGroup/PRS domain，不写 BMC 功率。服务就绪、网络 GET、TLS 和身份验证不能替代动态功率闭环验收；模拟器认证与 fixture 限制见 [BMC 访问说明](hardware-sim/bmc-access.md)。已有隔离全栈验证复用了物理 K3s，尚无另一台空白 OS/K3s 首装验证。带日期的结果和迁移实录见 [操作历史](docs/operation-history.md)，报告在 runtime。

## Git 与运行材料

Git 保留公开源码、模板、固定下载清单和构建配方。下载包、SDK/vendor、生成配置、密码/Secret、证书/私钥、kubeconfig、data、日志和报告均不提交，跟踪范围见 [.gitignore](.gitignore)。验证报告是证据，不是安装依赖。

新实例生成新身份和空数据；已有实例维护保留原密码、CA、JWT、values 与数据，不重播历史初始化或迁移命令。
