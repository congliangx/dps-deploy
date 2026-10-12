# DPS 访问与现有实例维护

**安装完成后，从本页进入 Kubernetes、DPS CLI 和浏览器 UI，并进行日常状态检查与维护。** 安装路线见 [installstep.md](../installstep.md)；本页使用已经安装好的服务和原有身份。

以下命令适用于按本仓库 Lab 配置安装的实例。源码根由脚本位置确定，主机、域名、namespace、runtime_root 等公开参数来自根目录 [deployment.yaml](../deployment.yaml)。使用客户已有 Kubernetes 或其他服务时，按 [已有基础设施对接](existing-infrastructure.md) 保留客户的 kubeconfig/context、账号和证书；不要用 Lab 环境脚本覆盖客户集群选择。

## 1. 每次新开 SSH 会话，加载环境变量

先在自己的电脑上连接部署主机。下面是当前 L20-12 的示例；其他实例替换主机和用户，已经在部署主机的会话中则跳过这条连接命令：

~~~bash
ssh root@L20-12
~~~

登录远端后，进入实际 clone 的仓库根目录，并使用 Bash。下面源码路径只说明当前实例，其他实例替换为实际目录：

~~~bash
bash
cd /raid/vince/deploy
source dps-install/scripts/deployment-env.sh --config "$PWD/deployment.yaml"
~~~

source 让脚本导出的变量在**当前 Bash 会话**中生效。新开终端、重新 SSH 或切换用户后，需要重新加载；不需要在启动每条 kubectl 命令前重复加载。指定其他公开配置文件时，将 --config 的参数替换为该文件路径。配置中的相对 runtime_root 按 deployment.yaml 所在目录解析。

环境脚本只解析公开配置及派生路径，不安装服务、不读取密码，也**不会自动登录 DPS**。全量 install-from-zero 还会保存 runtime/dps-install/config/dps-env.sh；手工或组件独立安装不保证存在这个副本，因此统一使用仓库内的 deployment-env.sh 加载环境。

查看公共地址、路径和集群选择：

~~~bash
printenv DPS_SOURCE_ROOT DPS_RUNTIME_ROOT DPS_DEPLOYMENT_CONFIG
printenv KUBECONFIG DPS_KUBE_CONTEXT DPS_NAMESPACE DPS_RELEASE
printenv DPSCTL_HOST DPSCTL_PORT DPSCTL_CA_CERT_PATH
printf 'UI: https://%s\nAPI: https://%s:%s\n' \
  "$DPS_UI_NAME" "$DPSCTL_HOST" "$DPSCTL_PORT"
~~~

| 环境变量 | 来源及用途 |
| --- | --- |
| DPS_SOURCE_ROOT | 脚本所属的仓库根目录 |
| DPS_RUNTIME_ROOT | deployment.yaml 的 runtime_root，保存已生成配置、身份和数据 |
| KUBECONFIG | runtime/dps-install/config/kubernetes/kubeconfig.yaml，供 kubectl 和 Helm 连接集群 |
| DPS_KUBE_CONTEXT / DPS_NAMESPACE / DPS_RELEASE | 配置中的 kube_context、namespace、release |
| DPSCTL_HOST / DPSCTL_PORT | 配置中的 api_name，以及本 Lab 的 HTTPS/gRPC 端口 443 |
| DPSCTL_CA_CERT_PATH | runtime/dps-install/config/tls/ca.crt，DPS CLI 的服务端信任 CA |
| DPSCTL_CREDENTIALS_PATH | runtime/dps-install/config/dpsctl/credentials.yaml，CLI 登录后的会话文件 |
| DPSCTL_LOG_FILE | runtime/verification/logs/dpsctl.log，CLI 私密日志 |

这里的 runtime 表示 DPS_RUNTIME_ROOT 对应的目录，不是一个固定目录名。加载成功不代表集群、证书或账号已就绪；后续连接仍需使用安装阶段生成的文件。

## 2. 访问 Kubernetes

保持上一步的 Bash 会话，查询节点、DPS 工作负载、持久卷和 Helm release：

~~~bash
kubectl --context "$DPS_KUBE_CONTEXT" get nodes
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get pods,pvc
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
~~~

kubectl 和 Helm 从 KUBECONFIG 读取 Kubernetes API 地址及认证材料，--context 选择配置中的目标集群。这些命令只查询状态。当前 L20-12 实例的 context 是 dps-l20-12，namespace 和 release 都是 dps；其他实例以自身 deployment.yaml 为准。

## 3. 使用真实 LDAP 账号登录 DPS CLI

保持已经加载的环境，调用登录入口，再查询 DPS：

~~~bash
bash dps-install/scripts/dps-login.sh --config "$DPS_DEPLOYMENT_CONFIG"
dpsctl server-version
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~

dps-login.sh 读取 runtime/dps-install/config/dps-access.json 中的真实 LDAP 用户名和密码，通过 password-stdin 登录；成功后只显示账号及私密会话文件路径，不打印密码或 token。登录写入的会话文件由 DPSCTL_CREDENTIALS_PATH 指定。令牌失效时重新执行登录命令即可，不需要重建 LDAP 或再次生成密码。

这个 Lab 登录入口还会核对 runtime values.yaml 已启用 LDAP。客户使用已有目录或其他认证方案时，按 [对接指南](existing-infrastructure.md) 使用实际账号和认证设置；本仓库生成的 dps-access.json 不是客户现有身份服务的通用凭据文件。

## 4. 浏览器访问 DPS UI

在第 1 节打印的 UI 地址打开浏览器，用 dps-access.json 对应的真实 LDAP 用户登录。浏览器所在电脑必须能连接部署入口，并将配置的 API/UI 域名解析到 deployment.yaml 的 host_ip；可以使用 DNS，或在**浏览器所在电脑**的 hosts 文件添加映射。

当前 L20-12 实例的 hosts 示例为：

~~~text
10.6.131.43 api.dps.lab ui.dps.lab
~~~

该实例的 UI 地址为 **https://ui.dps.lab**。上面的 IP 和域名只说明当前实例，其他安装使用自己的 host_ip、api_name 和 ui_name。部署主机上的 hosts 配置不会自动作用于另一台电脑。

将 runtime/dps-install/config/tls/ca.crt 这份**公开 CA 证书**导入客户端操作系统或浏览器的受信根证书存储；DPS CLI 已通过 DPSCTL_CA_CERT_PATH 使用同一份 CA。客户入口使用现有受信 PKI 时，按客户证书链配置。无需把服务端私钥、kubeconfig 或 CLI token 复制给浏览器。

## 5. 安装后的文件在哪里

本 Lab 的访问材料位于 DPS_RUNTIME_ROOT/dps-install/config。当前 L20-12 的 DPS_RUNTIME_ROOT 是 /raid/vince/deployed-test，因此对应目录为 /raid/vince/deployed-test/dps-install/config。

| config 下的文件 | 用途与产生阶段 |
| --- | --- |
| kubernetes/kubeconfig.yaml | Kubernetes API 地址及访问凭据；K3s 安装/refresh-kubeconfig 阶段生成 |
| tls/ca.crt | DPS HTTPS/gRPC 的公开受信 CA；DPS 证书准备阶段生成或由已有 PKI 提供 |
| dps-access.json | 真实 LDAP 用户名和密码；[LDAP 准备阶段](manual-ldap.md)生成，供登录脚本读取 |
| dpsctl/credentials.yaml | DPS 登录后取得的会话凭据；dps-login.sh 成功后保存，区别于 LDAP 原始账号密码 |
| values.yaml | 本 Lab 当前安装的 DPS Helm 输入；DPS 配置准备阶段生成 |
| dps-env.sh | 全量 install-from-zero 保存的环境副本；日常使用仓库内 deployment-env.sh 即可 |

kubeconfig、账号密码和会话文件属于私密运行材料，不提交 Git。dps-access.json 和 CLI 会话文件的权限为 600。管理员可在受控环境中从原账号交付材料获取 UI 登录密码，不需要将密码输出到共享终端、文档或报告中。DPS 账号不是模拟 BMC 的密码；本 Lab 的 dcpower-users 组映射 admin，错误密码会被拒绝，有效组外用户没有受保护接口权限。

其他运行材料也保存在所选 runtime 中：

- BMC URL/模拟用户名/密码：dps-install/config/bmc-endpoints.csv 和 bmc-credentials.json，说明见 [BMC 访问](../hardware-sim/bmc-access.md)。
- 独立 PostgreSQL 身份：dps-install/config/postgresql-credentials.json；CA 为 postgresql-ca.crt。
- 独立 LDAP 身份、配置和 TLS：dps-install/config/ldap。
- Core/Agent/Ingress/JWT：dps-install/config/tls。
- 数据库、LDAP、原生 K3s 与持久卷数据：dps-install/data。
- 固定资源下载/构建输出：dps-install/packages；日志、报告与历史归档：verification。

## 6. 日常状态检查、日志和维护入口

先完成第 1 节的环境加载。下面的 Compose 查询各自独立，**只执行已经部署的本 Lab 组件对应代码块**；没有模拟 BMC、或复用客户 PG/LDAP 时跳过其本地 Compose 查询，按实际服务的维护方式查看状态。

已部署本 Lab BMC 模拟器：

~~~bash
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
~~~

已部署本 Lab PostgreSQL：

~~~bash
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
~~~

已部署本 Lab OpenLDAP：

~~~bash
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
~~~

DPS 集群资源与事件的只读查询：

~~~bash
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get deployments,statefulsets,services,ingress
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get events --sort-by='.lastTimestamp'
~~~

Pod 日志可按 get pods 的实际名称使用 kubectl logs 查询，K3s 日志由 journalctl -u k3s 查看，DPS CLI 日志由 DPSCTL_LOG_FILE 指定。

备份、服务启停及配置维护入口见 [脚本说明](scripts/README.md)，包括 PostgreSQL Core/PRS dump 和 LDAP LDIF 备份；原生命令与参数说明见 [PG 手册](manual-postgresql.md)、[LDAP 手册](manual-ldap.md)、[DPS 手册](manual-install.md) 和 [BMC 手册](../hardware-sim/manual-install.md)。日常检查不需要重新执行首次安装脚本。变更前核对目标 runtime、namespace/project 和现有身份，备份相关配置及数据，保留原密码、CA、JWT 和持久数据。

按实际组件范围选择验收见 [verification](../verification/README.md)；报告和日志属于 runtime，不是安装依赖。当前拓扑保持 inactive，无资源组/PRS domain；例行状态检查不激活拓扑，也不写 BMC 功率。服务就绪与严格 TLS、真实 LDAP、数据库/S3 集成验证的范围，与动态功率闭环分别说明。

历史操作及路径迁移见 [操作历史](../docs/operation-history.md)。
