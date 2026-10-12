# DPS 0.9 / 4 rack GB300 手工安装

本仓库提供在物理机安装原生 K3s、独立 PostgreSQL/OpenLDAP、DPS 0.9 + PRS，以及 SDK GB300 BMC 模拟器的公开源码与手工步骤。SDK 仅模拟硬件，DPS 由明确的 Helm 命令安装。

首次部署从 [installstep.md](installstep.md) 开始；该文件只包含可重复安装步骤。完整历史实录、失败修复与带日期验收已迁入 [docs/operation-history.md](docs/operation-history.md)，不能把其中一次性迁移命令当成当前安装流程。

## 唯一配置与目录

只编辑根 [deployment.yaml](deployment.yaml)：主机/IP/网卡、namespace/release、域名/AgentId、端口/子网、固定版本及 Compose project 都从这里读取。

| 位置 | 内容 |
| --- | --- |
| /raid/vince/deploy | Git 源码、公开模板、固定包来源/SHA/digest、文档、安装/维护/验证脚本 |
| /raid/vince/deployed-test | deployment.yaml 的 runtime_root：下载包、生成配置/证书/密码/Secret、数据、systemd 副本、日志/报告/archive |
| runtime/hardware-sim/runtime | 独立 BMC config、nodes、nginx、Compose、TLS |
| runtime/dps-install/config | values、拓扑、PG/LDAP/TLS/PRS 输入、kubeconfig 与私密访问凭据 |
| runtime/dps-install/data | 独立数据库、K3s/containerd/kubelet/local-path、备份 |
| runtime/verification | 可复验结果、日志、历史和临时材料 |

源码与 runtime_root 不能相同。系统软件按机制使用 /usr/local/bin 与 /etc/systemd，副本/缓存/数据在 runtime；不用 k3d/kind 节点容器。

~~~bash
ssh root@L20-12
cd /raid/vince/deploy
# 使用 root Bash；python3-yaml 是配置解析器所需的 OS 包。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

请先进入实际 clone 的仓库根目录；上述 cd 仅为 L20-12 示例。其他手册从当前 Git 仓库推导源码根，不需逐份改路径。

## 手工安装顺序

1. [主机、固定 artifact 下载、原生 K3s](dps-install/manual-prerequisites.md)：curl/SHA、docker pull/build、物理节点与 containerd 镜像。
2. [硬件模拟](hardware-sim/README.md)：72 URL、随机 BMC 密码、新 CA、nginx/Compose 与只读 Redfish 检查。
3. [独立 PostgreSQL](dps-install/manual-postgresql.md)：TLS/SCRAM、非 superuser dps、Core/PRS 四库、持久化与备份。
4. [独立 OpenLDAP](dps-install/manual-ldap.md)：用户/组/只读 bind、LDAPS、客户端 TLS 与备份。
5. [DPS / PRS](dps-install/README.md)：13 Secrets、values、Helm、真实 LDAP 登录、电源类型、4 rack inactive 拓扑与 PRS=true。
6. [独立验证](verification/README.md)：安装输入与验证脚本/结果分开，健康 GET 与动态功率控制分开。

每个组件都有完整原生命令、说明和预期结果；仓库自编安装脚本不作为手工步骤的前置黑盒。可选脚本索引在 [scripts/README.md](dps-install/scripts/README.md)。[from-zero.md](dps-install/from-zero.md) 说明首次实例与维护的区别。

## 已验证范围与现有实例

L20-12 为实际单节点 Kubernetes；DPS 0.9.0、Power Steering 2.1.0、SeaweedFS 4.18、独立 PG 17.11/OpenLDAP 2.6.10。DPS 使用真实 LDAP 用户 dps-lab、组映射 admin，OIDC 关闭。API https://api.dps.lab、UI https://ui.dps.lab，客户端须解析到配置中的 host_ip 并信任 runtime/dps-install/config/tls/ca.crt。

2026-10-12 空源码副本的新身份/新数据隔离全栈验收 44/44，通过复用现有物理 K3s；PG 独立 33/33、LDAP 独立 24/24；完整重入 46 份证书/密钥/凭据/Secret 内容及数据库保留。该轮没有另一台空白 OS/K3s 首装验收。精简/详细证据在 runtime/verification；日期与完整操作见历史记录。

4 rack / 72 节点 / 288 GPU / 144 CPU 是模拟硬件。拓扑默认并保持 inactive；PRS 部署开启、尚无活跃 ResourceGroup/domain。BMC/Agent 网络严格 TLS GET 成功不代表 Core→Agent 健康派发或动态功率控制已验证。模拟器不强制认证，fixture 固定型号/UUID 的限制见 [BMC 访问说明](hardware-sim/bmc-access.md)。

2026-10-12 已保留原身份/数据完成 runtime 迁移：9 工作负载 Ready、4 PVC Bound；12:11 的全栈 43/43、PRS 35/35 与身份/路径 11/11 通过。报告在 /raid/vince/deployed-test/verification/reports，本次实录追加在 operation-history。

## Git 与私密输入

Git 保留必需脚本、公开拓扑/values 模板、deployment.yaml、固定下载清单与 LDAP 构建配方；网络下载包、SDK/vendor、运行数据、密码/Secret、证书/私钥/kubeconfig、日志/报告/archive 均留 runtime。报告是验收证据，不是安装依赖。

新实例按手工步骤生成新身份与空数据；已有实例使用其保存的身份、values 和数据，不重建 CA/JWT/账号或重播历史迁移。当前跟踪范围以根 [.gitignore](.gitignore) 为准。
