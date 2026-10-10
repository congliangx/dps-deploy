# 独立 OpenLDAP 安装与维护

此组件独立于 DPS Helm release，运行在 L20-12。使用固定官方 Debian 13 基础镜像及 Debian OpenLDAP 2.6.10 包自行构建镜像，未接入公司 LDAP。

- LDAPS：`ldaps://10.6.131.43:1636`，证书 SAN 包含 `ldap.dps.lab` 与 `10.6.131.43`。
- Base DN：`dc=dps,dc=lab`。
- 用户目录：`ou=users,dc=dps,dc=lab`；组目录：`ou=groups,dc=dps,dc=lab`。
- 登录用户 `dps-lab` 使用现有 `config/dps-access.json` 中的密码；其完整 DN 为 `uid=dps-lab,ou=users,dc=dps,dc=lab`，属于 `dcpower-users`。
- `dps-noaccess` 是有真实密码、无 DPS 授权组的验证账号。
- DPS 绑定账号为 `uid=dps-bind,ou=services,dc=dps,dc=lab`，只能读取目录，不能读取密码哈希或修改条目。

## 文件与凭据

`credentials.json`、`admin.password`、`bind.password`、`user.password`、`noaccess.password` 均为600权限；私密目录为700。不要将这些文件写入普通日志或版本控制。

`tls/ca.crt` 为客户端需要信任的公开 CA；LDAP服务端证书与私钥为 `tls/server.crt` 和 `tls/server.key`。CA由现有DPS项目CA签发，LDAP使用独立服务端身份。

`dps-ldap-bind-secret.yaml`（`dps-ldap-bind/bind-password`）及 `dps-ldap-ca-secret.yaml`（`dps-ldap-ca/ca.crt`）是DPS所需安装输入，由DPS命名空间准备脚本应用。独立LDAP启停不依赖Kubernetes。

`deployment.json` 保存固定镜像ID、Debian基础digest、包版本及离线包SHA256；`packages/ldap/openldap-2.6.10-runtime.tar` 保存LDAP运行镜像和基础镜像。离线构建文件、包及校验清单位于 `packages/ldap/build/`。

## 安装与启停

以下命令在远程机器执行：

```bash
cd /raid/vince/deploy
python3 dps-install/scripts/prepare-ldap.py
dps-install/scripts/ldap-start.sh
dps-install/scripts/ldap-status.sh
```

准备脚本复用已有凭据与证书，校验固定镜像身份；必要时加载离线镜像。容器为 `dps-openldap`，重启策略 `unless-stopped`，slapd以UID10001运行，仅绑定LDAPS入口。首次启动仅在空目录初始化，重启保留现有目录；不重新应用初始化LDIF。

停止与重新启动：

```bash
dps-install/scripts/ldap-stop.sh
dps-install/scripts/ldap-start.sh
```

LDAP停止期间DPS新登录无法完成LDAP认证。密码变更应通过LDAP管理操作完成，不能通过重新生成初始LDIF改变已有用户。

## 备份与恢复

```bash
dps-install/scripts/ldap-backup.sh
```

备份写入 `dps-install/data/ldap-backups/ldap-<UTC时间>.ldif`，权限600，包含密码哈希，需保护。当前MDB数据在 `dps-install/data/ldap/`。MDB支持运行中slapcat读取备份；目录多步修改期间应选择合适的备份窗口。[OpenLDAP维护指南](https://openldap.org/doc/admin26/maintenance.html)

恢复必须停用目标目录服务，在新空目录中使用匹配镜像的slapadd导入备份，验证后再切换；保留原数据以便回退。不要向在线生产目录执行slapadd。[slapadd说明](https://manpages.debian.org/trixie/slapd/slapadd.8.en.html)

目前完成备份及隔离环境的 `slapadd -u` 干运行检查，未覆盖恢复生产数据；结果在 `verification/reports/ldap-backup.json`。LDAP正反登录、授权组、只读ACL和TLS验证报告在 `verification/reports/ldap-installation.json`；检查工具 `verification/scripts/verify-ldap.py` 不参与安装。
