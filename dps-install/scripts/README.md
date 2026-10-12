# 安装与维护脚本索引

安装入口从 [installstep.md](../../installstep.md) 选择；各 manual 说明脚本阶段、产物和完整原生命令。客户已有基础设施使用 [对接指南](../existing-infrastructure.md) 的 values、Secret 和 kubeconfig，不用完整 Lab 链接管已有服务。

**安装后的环境加载、登录和日常查询见 [dps-access.md](../dps-access.md)。** 本页只列工具职责；查询前先加载环境并登录，维护保留原身份与数据。

## 配置

deployment-env.sh / deployment_context.py 从 [deployment.yaml](../../deployment.yaml) 解析主机、namespace/release、域名、端口、版本、Compose project 和运行路径。配置中的 runtime_root 由用户选择，布局及相对路径规则见 [根 README](../../README.md)。在 root Bash、源码根加载：

~~~bash
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

生成配置、下载、data、日志和报告写入 runtime，不提交 Git。

## 独立组件的一键入口

先配置 deployment.yaml，完成 installstep 第 0–1 节的主机依赖。以下入口相互独立，只运行需要新建的组件：

~~~bash
# 三个互相独立的入口：只执行自己缺少且准备新建的组件。
bash hardware-sim/scripts/install-bmc.sh --config deployment.yaml
bash dps-install/scripts/install-postgresql.sh --config deployment.yaml
bash dps-install/scripts/install-ldap.sh --config deployment.yaml
~~~


各入口执行固定包下载/构建、归属检查、身份与配置生成、Compose 启动和基本自检；Secret YAML 只落盘，不安装 K3s/DPS 或应用集群 Secret。BMC 使用两个固定镜像，PG 使用其固定镜像，LDAP 从固定 base/17 包/配方构建。

脚本管理且配置完整一致的实例允许保留身份重入；手工或历史实例使用原配置维护。独立组件启动后按 DPS 手册/对接指南继续，不接续整套 install-from-zero 初始化。脚本与手工安装二选一。

## 新实例安装与配置生成

| 工具 | 用途 |
| --- | --- |
| install-component.py + install-bmc.sh / install-postgresql.sh / install-ldap.sh | 独立组件下载、生成、启动和自检 |
| install-from-zero.sh / install-from-zero.py | 完整 Lab：新身份、物理 K3s、独立 Docker 服务、Helm、LDAP 登录、inactive 拓扑与 PRS |
| install-host-dependencies.sh | OS 依赖、Docker/Compose v2、Python/YAML、OpenSSL |
| download-artifacts.py | 固定 chart、11 镜像、17 deb、LDAP 构建与 image ID；拒绝冲突缓存 |
| prepare-bmc-fresh.py | 蓝图渲染、新密码/CA、72 路由与 Compose |
| prepare-postgresql.py | PG 密码/CA、四库、TLS/SCRAM、数据目录与 Secret 输入 |
| prepare-ldap-fresh.py | LDAP 用户/组/bind、LDAPS、凭据与 Secret |
| prepare-dps-fresh.py | DPS/Agent/Ingress/JWT/S3 身份、values 与 Secret |

prepare 工具生成输入，不启动服务。首次入口不接管无归属的旧身份/data，不删除归属状态文件绕过保护。完整入口和组件入口可用 --help 查看参数；执行范围见 [from-zero.md](../from-zero.md)。

## 安装与维护工具

| 工具 | 用途 |
| --- | --- |
| install-tools.py / install-dpsctl.sh | 校验安装官方工具或提取匹配 dpsctl |
| install-kubernetes.sh / refresh-kubeconfig.py | 原生 K3s/systemd、runtime 数据与私密 kubeconfig |
| kubernetes.sh | K3s 状态/启停；stop 不保证所有 containerd 工作负载停止 |
| stage-runtime-images.py / stage-prs-images.py | 固定镜像导入 K3s containerd |
| postgresql-start.sh / postgresql-status.sh / postgresql-stop.sh | PG Compose 维护 |
| postgresql-backup.sh / postgresql-backup-prs.sh | Core/PRS 私密 custom dump |
| prepare-prs-databases.py | PRS 三库、角色权限与限定来源 hostssl/SCRAM |
| ldap-start.sh / ldap-status.sh / ldap-stop.sh / ldap-backup.sh | LDAP Compose 维护与私密 LDIF 备份 |
| prepare-ldap.py / build-ldap.sh | 原有 LDAP 输入/固定镜像维护；新实例用 fresh 或手工路线 |
| prepare-ldap-client-tls.py | Core 0.9 所需的 LDAP 客户端证书/key |
| configure-ldap-auth.py | 维护 LDAP 认证配置并核对已有 JWT |
| prepare-certificates.py / prepare-namespace.sh | TLS/JWT、namespace 与外部 Secret |
| configure-prs.py | PRS、PG TLS、内部 S3 与 Controller LDAP 配置 |
| install-dps.sh | 显式 Helm upgrade --install；只查状态无需运行 |
| dps-login.sh | 读取私密凭据，通过 password-stdin 登录 LDAP |
| register-devices.sh | 登记 33kW/95% 电源类型；匹配时不写，差异时拒绝 |
| import-topology.sh | 首次导入并核对 72 AgentId，保持 inactive |
| update-topology.sh | 用 current hash 更新关系；匹配时不写，保持 inactive |

变更前核对目标实例并备份，审阅现有 values 与 Helm 渲染后再明确升级；不要用重新生成身份代替维护。维护查询、原生命令和文件位置见访问文档及 [PG](../manual-postgresql.md)、[LDAP](../manual-ldap.md)、[DPS](../manual-install.md)、[BMC](../../hardware-sim/manual-install.md) 手册。

[验证脚本](../../verification/README.md) 与部署入口分离，报告不是安装依赖。拓扑默认 inactive，安装/维护不自动激活或写 BMC 功率。旧 LDAP/PRS 迁移、故障和带日期验收见 [操作历史](../../docs/operation-history.md)。
