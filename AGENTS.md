# DPS 0.9 / GB300 模拟环境工作约定

## 当前任务与目录

安装入口必须先总结组件并允许客户按现有环境选择新建或复用：真实 BMC 不需要模拟器，已有 K8s/PG/LDAP/PKI/S3 不重建。客户对接在自选 Helm values、namespace Secret、kubeconfig/context 中完成；deployment.yaml 是本仓库 Lab 脚本统一参数，不代替客户全部应用配置。Lab 的 13 Secret/9 workload/4 PVC 不是通用固定要求。按需 Secret 引用与原生命令见 [已有基础设施对接](dps-install/existing-infrastructure.md)。本次仅文档整理，不调整当前 L20-12 服务配置、身份或数据。

当前 L20-12 实例按用户要求保持仓库工作目录干净：源码在 /raid/vince/deploy，下载、生成配置、证书、密码、Secret、data、日志、报告与历史归档在 /raid/vince/deployed-test，使用 ssh root@L20-12。这组路径只描述当前实例，不限制其他用户的安装目录。源码根从脚本位置推导；运行参数由唯一的 [deployment.yaml](deployment.yaml) 读取，不在各脚本固定主机/IP/端口/目录。runtime_root 支持绝对路径或相对 deployment.yaml 所在目录的路径，可与源码同根、位于源码子目录、源码外部或其上级目录；CLI --runtime-root 的相对路径按执行目录解析。

所有实际部署与验证均在远端执行。本机只连接并同步本约定。系统服务/二进制按系统机制放在标准路径；系统单元的配置副本和服务数据仍属于 runtime。当前运行目录与默认设置以 deployment.yaml 为准。

- dps-install/scripts/deployment_context.py 提供 source_path、runtime_path 和统一设置；shell 通过 deployment-env.sh 加载同一配置。
- Git 跟踪脚本、公开模板/资源清单、节点蓝图和文档；用户可以选择同根、仓库内专用 runtime 子目录或其他位置，生成物均不提交。公开模板与生成配置路径必须区分，支持同根部署时不得覆盖源模板。本实例继续使用现有外置 runtime，不为改进通用目录配置而搬迁服务或数据；不通过 symlink/bind mount 把其运行材料放回当前仓库。
- 必要安装输入/数据分别在 runtime/dps-install/config、packages、data；硬件模拟输出在 runtime/hardware-sim；报告/log/archive 在 runtime/verification。
- 更改 host/runtime/namespace/project 等设置时先评估既有实例；fresh 入口不能接管无归属的旧 namespace、复用其他实例的域名或重置现有身份。
- 维护脚本是可选便利入口。installstep.md 和组件 README 必须给下载、配置、证书/密码、Secret、原生 docker/kubectl/helm/dpsctl 命令、解释与预期结果，不能只列自编脚本调用。
- installstep.md 只记录可重复安装流程；实际迁移、故障、日期和验收记录追加 docs/operation-history.md。完整私密证据留 runtime/verification，不提交 Git。
- 修改前备份必要配置/数据库，并保留失败实录；历史不得伪装成当前结果。更新此文件后同步本机 deploy/AGENTS.md。

## 运行实例与边界

DPS 0.9.0 手工 Helm 安装，原生物理单节点 K3s v1.34.12+k3s1，Core/Agent/UI、PowerSteering 2.1.0 与 SeaweedFS 4.18 共 9 个 workload。独立 Docker PostgreSQL 17.11、OpenLDAP 2.6.10、GB300 BMC Simulator 0.9.0 与 nginx 代理使用统一 project/container 设置。SDK 仅模拟 BMC，不能安装 DPS；不恢复 k3d/kind。

2026-10-12 运行目录迁移保留既有密码、CA/证书、JWT、数据库和 Kubernetes server datastore/token。K3s containerd/kubelet 缓存已归档重建，内部 kubeconfig 路径也已更新；4 个 PV/PVC 的 API 对象按原 claim 名称重建，数据文件迁移后完全相同，local.path 指向新 runtime，reclaim policy 为 Retain。不能声称 PV/PVC UID 未变化。

DPS 登录必须为真实 LDAP，禁止 alwaysAllow。密码不写 values 明文；CA/客户端证书按 Core 要求挂载，严格验证 LDAP/DPS/PG/BMC 对外 TLS。既有身份不自动轮换；记录过的 JWT、S3/BMC 密码或证书缺失必须恢复原输入，不能隐式生成另一套身份。

PRS 全局 true，headroom -15%，调度间隔 5 秒；Core 与三个 PRS 数据库都在独立 PG，verify-full/SCRAM，禁用 Helm 内建数据库。S3 为集群内认证 SeaweedFS，拒绝匿名读取。调度周期之间 idle 正常。

四 rack、72 计算节点、288 GPU、144 CPU。模拟器不强制密码检查且 fixture 有 GB200/Generic 字样/重复序列号限制，必须如实说明。拓扑保持 inactive，无资源组/PRS domain；不激活拓扑、不执行 BMC 功率 PATCH，不将服务和网络验收当作自动功率闭环验收。

拓扑输入从 source 蓝图按配置生成到 runtime；72 个 AgentId 必须在 Topology.Entities 关系中，通过官方 raw GetTopologyModel 检查。首次注册 33kW PowerSupply95_33000W 并导入；既有 inactive 拓扑若需要更新使用 current Hash 防冲突。0.9 CLI update 走 create、export 遗漏 AgentId 的实测限制仍适用。

## 官方依据与交付

以固定 DPS 0.9 chart/manifest 和官方文档为准，不猜测字段；模板渲染不代表运行成功。

- https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html
- https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/concepts/user_accounts.html
- https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/tasks/credentials-and-secrets-configuration.html
- https://docs.nvidia.com/datacenter/dps/versions/0.9/sdk/user/index.html

Git 仅交付维护源码、公开配置/模板和文档；真实 Secret、私钥、密码、JWT、kubeconfig、LDAP hash、下载包、SDK/vendor、data 与生成的验收报告不得提交。统一参数文件不含秘密。提交前审查实际 index blobs，确认源码闭包和秘密扫描。

本次用户已授权目录/服务路径迁移、文档整理和参数化，必要服务暂停/重建已执行。不得删除无关服务、重置系统或覆盖恢复运行数据库。新增破坏性且不在当前任务内的操作应先说明影响。此前 LDAP/PRS 启用授权继续有效，功率写入仍未获授权。
