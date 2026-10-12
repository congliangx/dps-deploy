# DPS 访问与现有实例维护

源码与部署目录分别由脚本位置和根目录 [deployment.yaml](../deployment.yaml) 决定。当前实例运行文件已迁入 /raid/vince/deployed-test；证书、密码和数据库继续复用，DPS release/namespace、域名和端口未改变。新实例的逐步安装见 [安装步骤](../installstep.md)。

## 加载本实例环境

在仓库根目录执行：

~~~bash
source dps-install/scripts/deployment-env.sh
printf 'Runtime: %s\nUI: https://%s\nAPI: %s:443\n' \
  "$DPS_RUNTIME_ROOT" "$DPS_UI_NAME" "$DPS_API_NAME"
kubectl --context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" get pods,pvc
helm --kube-context "$DPS_KUBE_CONTEXT" -n "$DPS_NAMESPACE" list
~~~

环境文件只解析公开设置，不安装服务，也不读取或打印密码。客户端应将配置的 API/UI 域名解析到 host_ip，并信任 runtime 中 dps-install/config/tls/ca.crt；使用 UI 域名的 HTTPS 入口。管理账号由独立 LDAP 校验，凭据位于 runtime 的 dps-install/config/dps-access.json（600），不是模拟 BMC 的密码。

## 使用真实 LDAP 账号登录 CLI

~~~bash
export DPS_ACCESS_FILE="$DPS_RUNTIME_ROOT/dps-install/config/dps-access.json"
DPS_USERNAME=$(python3 -c 'import json,os; print(json.load(open(os.environ["DPS_ACCESS_FILE"]))["username"])')
python3 -c 'import json,os; print(json.load(open(os.environ["DPS_ACCESS_FILE"]))["password"])' |
  dpsctl --no-retry login --username "$DPS_USERNAME" --password-stdin
dpsctl server-version
dpsctl agent list
dpsctl topology list
dpsctl settings list
~~~

密码只从受限文件通过 stdin 传入，不置于命令行或文档中。CLI 会话写入 runtime 的 dps-install/config/dpsctl/credentials.yaml，默认日志写入 runtime/verification/logs。dcpower-users 组映射 admin；错误密码被拒绝，有效组外用户没有受保护接口权限。

## 运行内容与维护

- BMC URL/模拟用户名/密码：runtime/dps-install/config/bmc-endpoints.csv 和 bmc-credentials.json。
- 独立 PostgreSQL 身份：runtime/dps-install/config/postgresql-credentials.json；CA 是 postgresql-ca.crt。
- 独立 LDAP 身份、配置和 TLS：runtime/dps-install/config/ldap。
- Core/Agent/Ingress/JWT：runtime/dps-install/config/tls。
- 四个数据库、LDAP、原生 K3s 与四个持久卷数据：runtime/dps-install/data。
- 固定资源下载/构建输出：runtime/dps-install/packages；历史/日志/验收：runtime/verification。

当前拓扑 inactive，无资源组/PRS domain。服务就绪、真实 LDAP、严格 TLS、数据库和 S3 集成不等同于动态功率闭环；不通过例行维护激活拓扑或写 BMC 功率。

启停和备份入口见 [脚本说明](scripts/README.md)。操作前加载统一环境，核对容器/project、namespace 和 runtime 路径。不得重新生成原实例身份、清空数据或自动重放历史 JWT 轮换。历史操作和路径变化见 [操作历史](../docs/operation-history.md)。
