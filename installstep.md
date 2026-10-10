# 安装步骤：原生 K3s、独立 PostgreSQL / LDAP、DPS 0.9 与 PRS

更新时间：2026-10-10，Asia/Shanghai（UTC+08:00）。所有命令在 root@L20-12 的 /raid/vince/deploy 执行。

当前为物理节点 l20-12，K3s v1.34.12+k3s1；DPS 0.9.0 手动 Helm revision 5 deployed。Core、Agent、UI、Power Config/Controller 2.1.0 和 SeaweedFS 4.18 共 9 个工作负载 Ready。DPS 持久化 prs_enabled=true，headroom -15%、调度间隔 5 秒；PRS 部署与实际 Pod 集成 35/35 通过。PostgreSQL 17.11 和 OpenLDAP 2.6.10 各自独立 Compose。上午 LDAP 18/18、CLI/UI 认证授权 28/28 的历史结果保留；本次 PRS 验收含实际 LDAP 登录回归。4 rack / 72 节点拓扑仍 inactive，没有资源组或 PRS domain，未向 BMC 写功率。

本文件先列当前有效流程，再记录本次真实迁移及排障。PRS 启用前完整记录另存 [PRS 前安装实录](verification/archive/prs-enablement/20261010T164346+0800/installstep.md)。当前环境已部署完成，维护时按目的选择步骤，不必全部重跑，更不要重新导入已有拓扑或清空数据。此前原生安装与 alwaysAllow 阶段完整记录保存在 [切换前安装实录](verification/archive/ldap-auth-migration/20261010T102922+0800/installstep.md)；更早容器节点历史见 [原生迁移前记录](verification/archive/native-k3s-migration/installstep-through-native-migration.md)。

## 当前目录与安装输入

| 目录 | 用途 |
| --- | --- |
| hardware-sim/ | SDK、BMC 模拟器、运行配置、证书和启停入口 |
| dps-install/packages/ | DPS chart、工具、K3s、固定容器镜像和 LDAP 构建包 |
| dps-install/config/ | Helm values、拓扑、BMC、PG、LDAP、Kubernetes、Secret 和访问凭据 |
| dps-install/scripts/ | 必要安装及维护脚本 |
| dps-install/data/ | PG、LDAP、K3s 持久化数据及备份 |
| verification/ | 单独保存检查脚本、结果、日志及历史；安装不读取检查报告 |

官方依据：[安装](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html)、[用户与角色](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/concepts/user_accounts.html)、[Secret 与证书](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/tasks/credentials-and-secrets-configuration.html)。参数以实际下载的 0.9 chart 为准。

## 1. 连接与固定工具

~~~bash
ssh root@L20-12
cd /raid/vince/deploy
python3 dps-install/scripts/install-tools.py
bash dps-install/scripts/install-dpsctl.sh
source dps-install/config/dps-env.sh
~~~

工具为 Helm 3.22.0、kubectl 1.34.12、dpsctl 0.9.0。安装复用下载包并核对校验值。复用 chart packages/dps-0.9.0.tgz，SHA256 为 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef。未由 SDK 安装、升级或重置 DPS。现行流程没有 k3d/kind。

## 2. 物理机原生 Kubernetes

首次安装入口及日常状态入口如下；已有 K3s 不需要重装：

~~~bash
./dps-install/scripts/install-kubernetes.sh --download-only
./dps-install/scripts/install-kubernetes.sh
source dps-install/config/dps-env.sh
./dps-install/scripts/kubernetes.sh status
kubectl --context dps-l20-12 get nodes
~~~

K3s v1.34.12+k3s1 由 systemd k3s 运行，物理节点 l20-12 / 10.6.131.43；API https://10.6.131.43:6443，项目 kubeconfig 为 config/kubernetes/kubeconfig.yaml（600），context dps-l20-12。配置 config/kubernetes/k3s.yaml，systemd 配置副本 config/kubernetes/systemd，数据 data/kubernetes/{k3s,kubelet,storage}。使用独立 containerd，Docker 继续供 BMC/PG/LDAP 使用。服务已启用开机启动，未执行物理机重启验收。只验证单节点部署。

## 3. 独立 GB300 BMC 模拟器

~~~bash
python3 hardware-sim/scripts/generate-topology.py
python3 hardware-sim/scripts/configure-bmc-proxy.py
./hardware-sim/scripts/bmc-simulator.sh start
./hardware-sim/scripts/bmc-simulator.sh status
~~~

官方 SDK BMC Simulator 0.9.0 独立后端加 nginx HTTPS 路由，共 4 rack、72 计算节点、288 GPU、144 CPU；72 个节点端口 10.6.131.43:18443–18514。后续 DPS 使用 config/bmc-endpoints.csv、bmc-credentials.json、topology-4rack-dps09.json 及相关 Secret。模拟器不强制密码，GB300 fixture 部分文字/序列号仍为固定值；完整范围见 [BMC 访问说明](hardware-sim/bmc-access.md)。本次 LDAP 切换没有重启 BMC 或执行功率 PATCH。

## 4. 独立 PostgreSQL

~~~bash
./dps-install/scripts/postgresql-start.sh
./dps-install/scripts/postgresql-status.sh
~~~

PostgreSQL 17.11 独立容器 dps-postgresql；10.6.131.43:15432，数据库/应用角色 dps，应用角色非 superuser；TLS verify-full、SCRAM 密码、max_connections 200。初始化只在空数据目录执行，已有数据不重新初始化。配置 config/postgresql，数据 data/postgresql，私有凭据 config/postgresql-credentials.json，访问恢复说明见 [PG 文档](dps-install/config/postgresql/README.md)。

Helm values 必须 postgresql.enabled=false，global.postgresql 使用此外部服务和凭据 Secret。初次 DPS migration 已创建 25 张 public 业务表；表数是历史观察值，不作为所有版本的固定断言。

## 5. 独立 OpenLDAP

常规部署复用保存的固定镜像和现有凭据/数据：

~~~bash
python3 dps-install/scripts/prepare-ldap.py
./dps-install/scripts/ldap-start.sh
./dps-install/scripts/ldap-status.sh
~~~

prepare-ldap.py 必要时从 packages/ldap/openldap-2.6.10-runtime.tar 加载固定镜像，复用已有用户、密码、哈希和证书；拒绝目录数据存在但凭据缺失的状态。build-ldap.sh 是可选离线源码重建入口，并非每次部署必须执行；重建若镜像 ID 改变，先审查固定部署清单，不能直接继续。

- 独立容器 dps-openldap，OpenLDAP 2.6.10，官方 Debian 13 base，固定包 slapd/ldap-utils 2.6.10+dfsg-1。
- 端点 ldaps://10.6.131.43:1636；服务器证书含 ldap.dps.lab 和该 IP，使用项目 CA，禁止关闭 CA/主机验证。
- 配置 config/ldap/compose.yaml、slapd.conf、bootstrap.ldif，持久化 data/ldap；restart unless-stopped。未开明文 389。
- 根 DN dc=dps,dc=lab；用户 uid=dps-lab,ou=users,dc=dps,dc=lab；组 cn=dcpower-users,ou=groups,dc=dps,dc=lab（groupOfNames，member 为用户完整 DN）。
- DPS 只读服务账号 uid=dps-bind,ou=services,dc=dps,dc=lab，专用随机密码；不能写目录或读取密码哈希。
- config/ldap/credentials.json 保存管理员、绑定及用户凭据（600），dps-lab 复用原私有 config/dps-access.json 的强密码。普通文档不展示明文密码。
- dps-noaccess 是独立授权反例用户，不在允许组，只有密码认证能力而没有 DPS 受保护接口权限。

固定镜像 ID 为 sha256:68b0ec36cc46324ce44dd357ec634dcd3264a5c078e3ff97e4878db7206a7eab；运行包 SHA256 为 67b0fb5449f480255e552cd4cc0254b9f657723cc9b55673d91c1fb0b10d8b6d。来源和构建包清单保存在 config/ldap/deployment.json 与 packages/ldap。

## 6. LDAP 认证、证书与 namespace

~~~bash
python3 dps-install/scripts/configure-ldap-auth.py
bash dps-install/scripts/prepare-namespace.sh
python3 dps-install/scripts/stage-runtime-images.py
~~~

configure-ldap-auth.py 配置现有 values，准备 LDAP 客户端证书，并调用 prepare-certificates.py 复用现有项目 CA/Core/Agent/Ingress 证书。迁移 JWT key 只执行一次，通过 config/ldap-auth-migration.json 核对已提交公钥；后续重跑不会再次轮换。不要删除该状态文件或现有签名 key。

当前关键 values：

~~~yaml
dps:
  auth:
    authenticatorType: ldap
    auth_required_groups: dcpower-users
    oidc:
      enabled: false
  ldap:
    enabled: true
    serverUrl: ldaps://10.6.131.43:1636
    bindDn: uid=dps-bind,ou=services,dc=dps,dc=lab
    baseDn: dc=dps,dc=lab
    userFilter: "(&(objectClass=person)(uid={username}))"
    groupProfile: groupOfNames
    groupFilter: "(&(objectClass=groupOfNames)(member={userdn}))"
    groupAttribute: cn
    groupRoleMapping: dcpower-users=admin
    defaultRole: ""
    certSource: file
    tlsCaCert: /secrets/ldap/ca.crt
    tlsClientCert: /secrets/ldap/tls.crt
    tlsClientKey: /secrets/ldap/tls.key
~~~

完整 volumes、bindPassword、JWT、PG/BMC 配置以 config/values.yaml 为准。LDAP 密码通过 dps-ldap-bind 的 bind-password key 挂载；CA 和客户端证书/key 通过 dps-ldap-ca 与 dps-ldap-client-tls 的 projected.sources[].secret 只读挂载。Core 0.9 运行配置要求三份 TLS 文件齐全；客户端证书不表示 OpenLDAP 强制双向 TLS。没有开启 LDAP_INSECURE_TLS。

基础 namespace 准备应用 8 个原有外部 Secret 加 3 个 LDAP Secret；PRS 再增加 S3 和 Controller LDAP 凭据 Secret，当前共 13 个项目外部 Secret，不在终端打印 Secret data。stage-runtime-images.py 导入原生 containerd 所需镜像，LDAP 仍由 Docker 独立运行。

## 7. PRS 依赖与安装配置

首次启用或核对现有组件时：

~~~bash
python3 dps-install/scripts/prepare-prs-databases.py
python3 dps-install/scripts/stage-prs-images.py
python3 dps-install/scripts/configure-prs.py
bash dps-install/scripts/prepare-namespace.sh
~~~

prepare-prs-databases.py 只准备 dps_prs_config、dps_prs_config_staged、dps_prs_controller，Owner dps，保留原 DPS 业务库；HBA 仅增加限定来源的 TLS/SCRAM 规则，reload，不重启 PG。Config/Controller 实际镜像未提供 DATABASE__TLS 参数，使用标准 PGSSLMODE=verify-full、PGSSLROOTCERT=/secrets/postgresql/ca.crt 和只读 CA Secret。实际应用会话为 TLSv1.3，两个真实 Pod 的严格 TLS 连接已验收。

PRS 两个 chart 开关均开启，子 chart PostgreSQL 关闭。SeaweedFS 4.18 提供内部 S3 bucket dps-prs，随机凭据保存在 config/prs，禁止匿名读取；三个 PVC 为 1Gi/1Gi/10Gi，位于 data/kubernetes/storage。组件日志使用 emptyDir，避免默认 /storage/logs 外部路径。Controller 复用 dps-lab LDAP 账号，由 dps-prs-dps-auth Secret 加严格 DPS CA 访问 Core。

网络策略同时允许宿主机 PG 10.6.131.43:15432 和 Docker DNAT 后 172.30.90.2:5432；Controller 额外允许 Kubernetes API 10.6.131.43:6443 获取凭据。PG 服务端观察到的 172.30.90.1 是 Docker SNAT 来源，不能要求其等于 Pod IP。

固定 runtime 包 packages/prs/prs-2.1.0-runtime.tar 及其镜像 digest/hash 由 config/prs/runtime-images.json 记录。stage-prs-images.py 复用固定 Docker 镜像导入原生 containerd，不需要 SDK 部署；本次匿名下载成功，未使用或复制 NGC key。

## 8. 手动 Helm 安装/升级与真实登录

~~~bash
bash dps-install/scripts/install-dps.sh
bash dps-install/scripts/dps-login.sh
~~~

安装脚本执行的明确 Helm 命令是：

~~~bash
helm upgrade --install dps dps-install/packages/dps-0.9.0.tgz \
  --kube-context dps-l20-12 --namespace dps \
  --values dps-install/config/values.yaml --wait --timeout 10m
~~~

当前 revision 5 deployed，9 个工作负载 Ready。脚本核对 chart checksum、0.9 release、LDAP 已启用、defaultRole 空、OIDC 禁用、独立数据库，以及 PRS 启用时三库、严格 Controller LDAP/TLS 和外部依赖，拒绝误用 pending release。重跑此步骤会生成新的 Helm revision，日常登录无需重跑 Helm。

dps-login.sh 从 config/dps-access.json 读取真实用户名/密码，以 stdin 登录，同时检查退出码和 status.ok；密码不放 argv，不打印 token。JWT 文件 config/dpsctl/credentials.yaml 权限 600。真实 dps-lab 通过 LDAP 组获得 admin；旧 alwaysAllow token 已被撤销，已有浏览器会话需要重新登录。

已有 DPS 数据库的用户设置不会因 Helm 环境变量自动覆盖。本次 Helm Ready 后，显式执行并读回：

~~~bash
source dps-install/config/dps-env.sh
dpsctl --no-retry settings update --set prs_enabled=true
dpsctl --no-retry settings list
~~~

实际返回 prs_enabled=true、prs_headroom_percent=-15、prs_scheduler_interval_seconds=5。维护时若仅登录或核对状态，不必重复执行 update。PRS 内部服务为 Config http://dps-power-config.dps.svc.cluster.local:8000、Controller http://dps-power-controller.dps.svc.cluster.local:8001；不新增对外端口。

UI https://ui.dps.lab，gRPC api.dps.lab:443；客户端将两个域名解析为 10.6.131.43 并信任公开 CA config/tls/ca.crt。详细登录与 SSH 隧道见 [访问说明](dps-install/dps-access.md)。

## 9. 拓扑维护边界

已有拓扑 dps-gb300-4rack，不再次导入。共有 110 实体（72 ComputerSystem、32 PowerSupply、4 PowerDistribution、2 PowerDomain），72 个 AgentId 路由在服务端 Topology.Entities 关系对象中，默认 MaxLPS，当前 inactive。

首次新建拓扑时才执行 register-devices.sh 和 import-topology.sh；已有且 inactive 的拓扑若确需更新，使用 update-topology.sh，读取当前 Hash 防冲突。0.9 CLI update 实测走 create 路径、CLI export 遗漏 AgentId，故当前维护脚本调用官方 API。

LDAP 切换与本次 PRS 服务启用均未激活拓扑、未修改功率策略、未执行 BMC 功率写入。Core 经 Agent 的 BMC 检查/指标/功率闭环需要 active topology，本次不把该闭环列为已通过。Power Steering/PRS 已启用，Zapp、OIDC 继续禁用。

## 10. 独立验收与备份

下列命令是可选复验，属于 verification，不是启动/安装依赖：

~~~bash
python3 verification/scripts/verify-ldap.py
python3 verification/scripts/verify-ldap-auth.py
python3 verification/scripts/verify-prs-installation.py
~~~

当前报告：

| 报告 | 实际结果 |
| verification/reports/prs-installation.json | 35/35：PRS 全局开关、9 Ready、真实 Pod PG/LDAP/TLS/S3、登录回归 |
| verification/reports/prs-databases.json | 18/18：三库/权限与实际镜像主机网络 TLS 正反例，作用域见报告 |
| verification/reports/prs-render.json | 最终 chart 与运行配置合同核对 |
| --- | --- |
| verification/reports/ldap-installation.json | 18/18：绑定、密码正反例、ACL、严格 TLS |
| verification/reports/dps-ldap-auth.json | 28/28：CLI/UI session API、组权限、旧 token、健康 |
| verification/reports/dps-ldap-render.json | 当前完整 CA/client TLS 渲染与运行配置核对 |
| verification/reports/ldap-backup.json | 8 个目录条目，slapadd -u 离线备份校验 |
| verification/reports/dps-current-state.json | 当前物理节点、release、Pod、LDAP 与拓扑状态 |
| verification/reports/dps-delivery-status.json | 当前交付范围，历史和当前验收分开记录 |

正确 dps-lab 密码登录成功；CLI 错误密码/不存在账号 AUTHENTICATION_FAILED，UI 对应 HTTP401，空密码 UI400。真实组外用户可获得空角色令牌，但 CLI 受保护 RPC AUTHORIZATION_FAILED、UI 受保护接口 HTTP403。新 LDAP refresh 成功，旧 alwaysAllow access/refresh 均 HTTP401。UI 验收经真实 HTTPS session API，未声称浏览器视觉验收。

维护备份入口：

~~~bash
./dps-install/scripts/postgresql-backup.sh
./dps-install/scripts/postgresql-backup-prs.sh
./dps-install/scripts/ldap-backup.sh
~~~

备份位于 data/postgresql-backups（custom dump，生成时 pg_restore --list 校验）和 data/ldap-backups（LDIF，含密码哈希，600）。当前迁移前 PG 备份 dps-20261010T022922Z.dump，切换后备份 dps-20261010T025312Z.dump；LDAP 备份 ldap-20261010T023406Z.ldif 已完成离线校验。未覆盖恢复运行中的数据库/LDAP。备份文件名带实际时间；复跑会生成新备份。

## 2026-10-10 LDAP 切换真实实录

1. 10:29 +08:00：确认物理 K3s、现有 DPS/PG/BMC，修改前归档 AGENTS、文档、values、旧 JWT/凭据和脚本到 verification/archive/ldap-auth-migration/20261010T102922+0800；私密材料 600、目录 700。创建并校验 PG 迁移前备份。
2. 独立构建并启动 OpenLDAP 2.6.10，创建用户/组/只读 bind。首次容器配置使用 cap_drop ALL，初始化 chown 后 chmod 缺少 FOWNER 能力；仅补充所需能力，修复后 healthy。18/18 验收通过，8 条 LDAP 数据备份通过离线导入 dry-run 校验。
3. 10:35 +08:00：最初只配置 LDAP CA，Helm 模板可渲染，但 Core 实际启动失败，日志为 invalid tls_client_cert: file not found or not accessible。离线渲染不等于运行成功；该方案未作为当前交付。
4. 为 Core 准备独立 clientAuth 证书/key，使用同项目 CA，通过第三个 LDAP Secret 与 CA projected 挂载。一次性更换 JWT RSA 签名 key，保留旧私密凭据用于实际撤销验证。Core/Agent/Ingress 身份不轮换。
5. 中断本项目等待中的 Helm revision 2 命令，留下 failed revision 记录；按完整 TLS values 执行 revision 3。StatefulSet OrderedReady 的旧 CrashLoop Pod 未自动更新：核实期望模板含正确 CA/client 路径，旧 Pod 未就绪且 revision 不同后，仅删除 dps-server-0 让控制器按新模板重建，保留 PVC/数据库数据。随后 Core/Agent/UI Running/Ready，restart_count=0；revision 3 deployed。最终日志 verification/logs/dps-ldap-helm-upgrade-fixed.log；初次 CA-only values/log 保留 verification/archive/ldap-auth-migration/ca-only-attempt。
6. 验收脚本最初存在 CookieJar 名称遮蔽、缺少 UI Origin header 和组外账户预期错误；修正检查代码及预期后复验。旧失败报告/脚本保留 verification/archive/ldap-auth-migration/verification-before-fix，不能把初次检查失败记作服务已通过。
7. 10:52:29 +08:00：DPS LDAP 验收最终 28/28 通过：真实登录、授权角色、UI cookie/读取/logout、负向密码/账户、组外拒绝、刷新和旧 token401，DPS/数据库/Agent 健康。日志 verification/logs/dps-ldap-auth-verification.log，不记录密码/JWT。
8. 10:53 +08:00：显式执行生产 dps-login.sh 成功，保持用户凭据文件 600。创建并校验切换后 PG 备份 dps-20261010T025312Z.dump。当前文档改为独立 LDAP，更新工作约定和状态记录；旧完整安装记录已归档。
9. 本次没有改硬件模拟器、激活拓扑、调整功率策略、执行 BMC PATCH，也没有启用 Power Steering/PRS/Zapp。

## 2026-10-10 PRS 启用真实实录

1. 16:43:46 +08:00：按用户“打开 PRS”要求归档变更前文档、values、脚本和状态到 verification/archive/prs-enablement/20261010T164346+0800，另创建并校验 Core PG 备份 dps-20261010T084716Z.dump。旧 PRS 禁用约定由本次授权替代。
2. 创建三个独立 PRS 数据库及限定来源 TLS/SCRAM HBA，Owner dps，原 DPS 数据保留。实际 Config/Controller 2.1.0 镜像在主机网络下完成 18/18 数据库正反例检查，初始三库备份时间 20261010T085041Z。服务 Pod 部署后另验收其实际连接，不能把主机网络检查当作 Pod 验收。
3. 获取并导入固定 Power Steering 2.1.0、SeaweedFS 4.18、busybox 与 OTel 镜像，准备 S3 随机凭据与 Controller 真实 LDAP Secret，开启两个 chart 开关。S3 凭据只保存在 600 私密文件，不写公开文档。
4. 16:50:26 +08:00：首次 Helm revision 4 部署时，Config 因 PG connection refused 失败，Controller 等待 Config。NetworkPolicy 只放行宿主机 15432，但 Docker DNAT 后实际目标为 172.30.90.2:5432。添加这条精确规则；同时将 SeaweedFS 默认 master/filer 日志 hostPath 改为 emptyDir。只中断已确认的本项目 Helm 等待进程；revision 4 保留 failed，第一次 values/log 和当时产生的日志归档 first-upgrade。
5. 修复后手动升级 revision 5 deployed，9 工作负载全部 Ready。Config 在首次失败期间累计 6 次重启，保留该计数；其他最终 Pod 当时无重启。日志 verification/logs/prs-helm-upgrade-fixed.log。
6. Core 启动配置虽显示 PRS=true，但数据库原有用户设置仍为 false。确认拓扑 inactive、没有资源组后，显式执行 dpsctl --no-retry settings update --set prs_enabled=true；读回 true、headroom -15%、scheduler 5 秒。未激活拓扑、未写 BMC。
7. 首次检查报告 30/33，原因是验收代码错误假设 PV 必须 hostPath、scheduler 必须 running、PG 来源必须 Pod IP；实际为 K3s local PV、周期之间 idle、Docker SNAT。保留原报告与脚本到 verification-first-attempt，修正预期并新增两个真实 Pod verify-full 数据库探针。
8. 2026-10-10T17:05:41.804854+08:00：最终 35/35 通过。Controller 通过自身实际 SecretLoader、LDAP 和严格 DPS CA 读取真实拓扑；三库迁移表存在、应用 PG 会话 TLSv1.3，两个 Pod 严格 verify-full 连接成功；S3 Put/Get/Delete 与匿名读取拒绝成功，测试对象已删除；CLI/UI LDAP 登录、错误密码拒绝、Agent mTLS 和 Core 健康回归通过。Scheduler 正常运行周期，域清单为空。动态功率控制没有验收。
9. 17:06 +08:00：创建 Core 与三 PRS 库迁移后 custom dump，全部经 pg_restore --list 校验，文件时间 20261010T090629Z；详细路径/校验值见 verification/reports/prs-post-install-backup.json。将首次升级在 /storage/logs/seaweedfs/{master,filer} 产生的本项目日志移动到历史归档，现行组件日志不使用这些 hostPath。
10. 更新现行文档、工作约定、状态/交付报告并同步本机 AGENTS。必要安装输入保持 dps-install，检查/临时材料保持 verification；没有重启 K3s、PG、LDAP、BMC，没有轮换 JWT 或重新初始化任何服务。


## 2026-10-10 BMC 健康只读复检

按用户要求检查当前 BMC 健康；仅 GET，不进行 PATCH/POST、重启、拓扑激活或策略变更。

~~~bash
python3 verification/scripts/verify-bmc-inventory.py
python3 verification/scripts/verify-agent-pod-bmc.py
source dps-install/config/dps-env.sh
dpsctl --no-retry --grpc-timeout 20s check connection --topology dps-gb300-4rack
dpsctl --no-retry --grpc-timeout 20s check status
~~~

- 17:28:35 +08:00：主机通过严格 CA/端点身份验证读取全部 72 BMC，共 2232 GET。4 rack 每 rack 18 节点通过；readyz/livez、两个系统、两个 BMC Manager、HGX chassis 与 288 GPU/144 CPU Health=OK、State=Enabled，系统/chassis PowerState=On。功率读数、上下限、当前 setpoint 均有效。upstream GB200/Generic 文字及重复序列号为已知 fixture 限制，不代表真实硬件身份。
- 17:28:49 +08:00：实际 Agent Pod 网络 namespace 内严格 CA 验证全部 72 端点，1152 GET 通过。没有创建 debug/ephemeral 容器或修改 Pod spec；宿主机 Python 仅进入该 Pod 网络 namespace。
- DPS 当前拓扑仍 inactive。实际连接诊断返回 INVALID_OPERATION / no agent configuration available；节点状态查询返回 SERVER_NOT_STARTED / the server has not been started。保存原结果，不把 Core→Agent→BMC 健康派发标为通过；独立端点/Agent 网络通过不等于该链路通过。
- 独立 BMC 模拟器和 nginx 代理运行/健康、最近日志、Core/Agent Ready 另由 verification/reports/bmc-service-health.json 记录。最终分范围汇总见 verification/reports/bmc-health.json。细项在 verification-inventory.json、dps-pod-bmc-connectivity.json、bmc-dps-health-check.json。
- 修改前库存检查脚本及旧检查结果已归档 verification/archive/bmc-health-check/20261010T172833+0800；现行库存脚本改用公开 simulator-ca.crt 严格 TLS，并新增 service/system/manager/chassis 状态记录。没有改模拟器运行配置、凭据、功率限制或 DPS 功能开关。
