# 配置解析与可选维护工具

手工安装从根 [installstep.md](../../installstep.md) 开始，具体原生命令在 [主机/K3s](../manual-prerequisites.md)、[PG](../manual-postgresql.md)、[LDAP](../manual-ldap.md)、[DPS](../manual-install.md)。本目录自编脚本不作为步骤中的黑盒替代；它们仅是可选自动化/维护实现。

## 单一配置

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

deployment-env.sh / deployment_context.py只解析源码根deployment.yaml，导出DPS_SOURCE_ROOT/DPS_RUNTIME_ROOT、host/namespace/release/AgentId/域名/端口/网段/版本、3个Compose project及kubeconfig/DPSCTL路径。公开源码只放模板/固定清单；实际生成、downloads/data/logs/reports/archive全部在runtime。源码与runtime不是同一目录。

## 首次新实例可选实现

| 工具 | 用途 |
| --- | --- |
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
