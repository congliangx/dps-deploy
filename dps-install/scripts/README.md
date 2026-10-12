# 安装、配置解析与维护脚本

脚本安装或手工安装均从根 [installstep.md](../../installstep.md) 选择入口，具体原生命令在 [主机/K3s](../manual-prerequisites.md)、[PG](../manual-postgresql.md)、[LDAP](../manual-ldap.md)、[DPS](../manual-install.md)。本目录保存安装/维护脚本；完整 Lab 可以一条脚本执行，各 manual 解释对应阶段与产物，并保留逐步原生命令。

完整从零入口用于 Lab，不提供任意企业既有服务的选择式安装。客户对接已有 PG/LDAP/Kubernetes/真实 BMC 使用 [对接指南](../existing-infrastructure.md) 的自选 Helm values、Secret 和 kubeconfig，不运行完整 fresh 链重写其配置。

## Lab 脚本单一配置

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get pods,pvc
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" list
dpsctl server-version
dpsctl agent list
dpsctl topology list
~~~

deployment-env.sh / deployment_context.py读取deployment.yaml，导出DPS_SOURCE_ROOT/DPS_RUNTIME_ROOT、host/namespace/release/AgentId/域名/端口/网段/版本、3个Compose project及kubeconfig/DPSCTL路径。源码根从脚本位置推导，runtime_root由用户设置，支持绝对路径或相对配置文件目录的路径。例如.runtime是仓库内专用子目录，.是源码与运行材料同根，/srv/dps-lab是自选绝对目录；源码上级目录也可用。CLI --runtime-root的相对路径按执行目录解析。Git跟踪公开模板/固定清单，实际生成、downloads/data/logs/reports/archive写入runtime并排除Git。当前L20-12继续使用既有外置runtime。

## 独立组件的一键安装入口

先配置 deployment.yaml，并按根 installstep 第 0–1 节准备 Bash/root、Python/YAML、OpenSSL 和 Docker/Compose。下列入口各自完成该组件的下载/构建、归属检查、首次密码/证书/配置与 Secret YAML、Compose 启动及基本只读自检；不安装 K3s/DPS，也不向集群应用 Secret：

~~~bash
# 三个互相独立的入口：只执行自己缺少且准备新建的组件。
bash hardware-sim/scripts/install-bmc.sh --config deployment.yaml
bash dps-install/scripts/install-postgresql.sh --config deployment.yaml
bash dps-install/scripts/install-ldap.sh --config deployment.yaml
~~~

共用 install-component.py；各入口支持 --help 查看参数，不执行下载或安装。BMC 仅取两个固定镜像，PG 仅取其固定镜像，LDAP 从固定 base/17 包/配方构建。生成物仍进入 deployment.yaml 所选 runtime_root；后续 DPS 所需 namespace Secret/values 按各 manual 与 [已有环境对接](../existing-infrastructure.md) 处理。

已有手工/历史配置、数据或其他实例容器/网络不由首次入口接管；同一生产者管理、参数/身份完整一致的实例允许保留身份重入。独立组件安装不是整套 full bootstrap 的暂停模式，启动 PG/LDAP 后不要再调用 install-from-zero 接管，按手工 DPS/对接流程继续。全部组件的脚本与手工路线二选一，不重复初始化。

## 首次新实例可选实现

| 工具 | 用途 |
| --- | --- |
| install-component.py + install-bmc.sh / install-postgresql.sh / install-ldap.sh | 各组件独立下载、生成、启动与自检；Secret 只落盘，后续按手册对接 DPS |
| install-from-zero.sh / install-from-zero.py | 可选自动化链；下载/生成新身份→物理K3s→独立Docker→手动Helm→LDAP→inactive拓扑/PRS |
| install-host-dependencies.sh | OS依赖、Docker/Composev2/PythonYAML/OpenSSL |
| download-artifacts.py | 官方chart/11镜像digest/17固定deb、LDAP构建与本次ID；拒绝冲突缓存 |
| prepare-bmc-fresh.py | 公开nodes/topology→新密码/CA/72路由/Compose，无SDK/vendor依赖 |
| prepare-postgresql.py | 独立PG密码/CA、四库/TLS/SCRAM、持久化/Secret输入；不启动DPS |
| prepare-ldap-fresh.py | 新LDAP真实用户/组/bind、LDAPS与Secret；保留完整已有归属身份 |
| prepare-dps-fresh.py | 新DPS/Agent/ingress/JWT/S3、values与Secret，直接LDAP/PRS |

这些工具可读--help，并使用同一deployment.yaml。不要在已有非bootstrap身份/data上调用fresh生成；不能删除归属状态文件绕过保护。手工创建的实例属于手工管理，不自动假定producer拥有其身份。首次脚本的验证范围见 [from-zero](../from-zero.md)：2026-10-12隔离44/44只复用已有物理K3s，没有另一裸OS首装实测。

## 必要安装/维护实现索引

| 工具 | 用途 |
| --- | --- |
| install-tools.py / install-dpsctl.sh | 校验官方工具或提取匹配dpsctl |
| install-kubernetes.sh / refresh-kubeconfig.py | 原生K3s systemd与runtime数据、私密kubeconfig |
| kubernetes.sh | systemctl状态/启停；stop不保证所有containerd工作负载停止 |
| stage-runtime-images.py / stage-prs-images.py | 固定镜像导入K3s containerd |
| postgresql-start.sh / postgresql-status.sh / postgresql-stop.sh | 独立PG Compose维护 |
| postgresql-backup.sh / postgresql-backup-prs.sh | Core/PRS私密custom dump |
| prepare-prs-databases.py | 三PRS库与角色权限、限定来源hostssl/SCRAM |
| ldap-start.sh / ldap-status.sh / ldap-stop.sh / ldap-backup.sh | 独立LDAP Compose及私密LDIF备份 |
| prepare-ldap.py / build-ldap.sh | 原有独立LDAP输入/固定镜像的维护实现；新实例看fresh或手工手册 |
| prepare-ldap-client-tls.py | 满足Core0.9客户端证书/key要求 |
| configure-ldap-auth.py | 已有LDAP认证配置维护，核对现有JWT；普通重入不轮换身份 |
| prepare-certificates.py / prepare-namespace.sh | 稳定TLS/JWT/namespace与外部Secret |
| configure-prs.py | PRS/PowerSteering、严格PG TLS、内部S3与Controller LDAP |
| install-dps.sh | 显式Helm upgrade --install；日常状态查询不需升级 |
| dps-login.sh | 私密文件→password-stdin真实LDAP登录，token保持私密 |
| register-devices.sh | 33kW/95%电源类型，匹配不写、差异拒绝 |
| import-topology.sh | 首次验证/导入并核对72AgentId，保持inactive |
| update-topology.sh | 官方API/currenthash/no-force关系更新，匹配无写，保持inactive |

安装/维护不会依赖verification报告。验证入口独立放源码verification/scripts，默认输出runtime/verification。所有服务保持原密码/CA/JWT/data；历史alwaysAllow→LDAP轮换、PRS第一次启用和故障排查只在 [operation-history](../../docs/operation-history.md)。

## 当前维护的原生命令

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
kubectl -n "$DPS_NAMESPACE" get pods,pvc
helm -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
dpsctl settings list
~~~

需要配置变更时人工审阅runtime values、helm template，再明确upgrade；不用“重建”实现覆盖已有身份。拓扑默认inactive、无活跃RG/domain，BMC功率写入和动态控制不在安装范围。
