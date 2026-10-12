# DPS 0.9 前置要求与检查顺序

完整原生命令见 [manual-prerequisites.md](manual-prerequisites.md)，总步骤见 [installstep.md](../installstep.md)。本页列出安装前应达到的状态；历史带日期验收在 [operation-history](../docs/operation-history.md)。

## 平台与版本

| 项目 | 本方案 |
| --- | --- |
| OS/节点 | Ubuntu22.04/24.04 amd64、systemd；物理单节点原生K3s |
| K3s | v1.34.12+k3s1，Docker外的containerd，local-path/Traefik |
| 工具 | Helm v3.22.0、kubectl v1.34.12、dpsctl0.9.0 |
| DPS | chart0.9.0、Core/Agent/UI0.9.0，同版本 |
| PG | 独立17.11，4库Owner dps、非superuser、SCRAM/TLS verify-full |
| LDAP | 独立OpenLDAP2.6.10，真实用户/组/只读bind，LDAPS |
| PRS | chart依赖PowerSteering2.1.0；SeaweedFS4.18内部S3 |
| BMC | SDK simulator0.9、GB300 mockup/synthetic，4rack72节点 |

NVIDIA0.9要求Kubernetes≥1.31、PowerSteering使用Helm≥3.12及PG≥17；此表是本方案实际固定版本，不据此宣称其他新版本全部兼容。依据：[官方安装要求](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html)。

## 唯一部署参数与文件

源码根deployment.yaml规定runtime_root、主机、网卡、命名、端口/网段与版本；用deployment-env.sh导出，不另维护host/IP脚本常量。公开chart/images/deb校验清单在artifact-sources.json，values.example.yaml与topology公开模板只读。

下载包、生成config/tls/Secret/kubeconfig、数据/备份、日志/报告/archive写用户选择的runtime_root；可使用绝对路径（如/srv/dps-lab）或相对deployment.yaml目录的路径（如.runtime）；.表示源码与运行材料同根，上级目录也可用。Git不提交这些生成物。所有安装输入在runtime/dps-install/config或runtime/hardware-sim/runtime；验证报告不是前置依赖。文档中的地址10.6.131.43/15432/1636/18443与L20-12目录只是当前deployment例，实际取环境变量。

## 手工前置 gate

1. 主机管理网卡/IP、磁盘、systemd、Docker Compose v2准备；现有服务/端口/子网先清点。
2. curl下载验证chart SHA、工具SHA与固定11镜像digest/amd64；Debian17deb SHA与公开配方构建LDAP，不要求旧imageID。
3. 原生K3s实际节点Ready、local-path与Traefik；Docker镜像导入K3s独立containerd；kubeconfig600。
4. BMC72URL严格CA GET；模拟器不强制密码行为独立标明。
5. 独立PG四库/权限/HBA与verify-full实际连接，管理员/应用密码分开；两个内建chart PG禁用。
6. LDAP真实用户与授权组/只读bind、严格LDAPS，完整CA/clientcert/key投射输入；OIDC关闭。
7. DPS13Secret、values无秘密；API/UI域名路由无其他实例占用；Core/PRS/Docker网络可通。

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl get storageclass
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
~~~

安装前“没有DPSrelease”仅适用于新实例，不是已安装实例当前状态。准备检查通过才进入 [DPS手工安装](manual-install.md)。独立PG/LDAP和BMC不由SDK/Helm替你安装。

## 验证边界

2026-10-12空源码新身份/新数据的集群复用验证44/44，PG33/LDAP24；没有新裸OS/K3s首装实测。单节点无法证明多节点HA。inactive拓扑、Agentconnected、BMC网络GET与PRS部署开启不能替代Core→Agent派发/动态功率闭环测试。
