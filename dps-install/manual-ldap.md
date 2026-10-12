# 手工部署独立 OpenLDAP 与真实 DPS 用户

先完成 [OpenLDAP 固定镜像构建](manual-prerequisites.md)。本节初始化新的空 LDAP data；已有 data.mdb、用户密码或 CA 时只检查/维护，不覆盖重新生成。DPS 使用 LDAP，不连接公司目录，OIDC 关闭。

## 1. 生成四份密码与 LDAP TLS

~~~bash
ldap_cfg="$DPS_RUNTIME_ROOT/dps-install/config/ldap"
ldap_data="$DPS_RUNTIME_ROOT/dps-install/data/ldap"
test ! -e "$ldap_cfg/user.password"
test ! -e "$ldap_data/data.mdb"
mkdir -p "$ldap_cfg/tls" "$ldap_data"
chmod 700 "$ldap_cfg" "$ldap_cfg/tls" "$ldap_data"
for account in admin bind user noaccess; do
  openssl rand -hex 36 | tr -d '\n' > "$ldap_cfg/$account.password"
  chmod 600 "$ldap_cfg/$account.password"
done
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$ldap_cfg/tls/ca.key"
openssl req -new -x509 -sha256 -days 730 -key "$ldap_cfg/tls/ca.key" \
  -out "$ldap_cfg/tls/ca.crt" -subj "/CN=DPS Independent LDAP CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$ldap_cfg/tls/server.key"
openssl req -new -key "$ldap_cfg/tls/server.key" \
  -out "$ldap_cfg/tls/server.csr" -subj "/CN=ldap.dps.lab"
cat > "$ldap_cfg/tls/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:ldap.dps.lab,DNS:$DPS_HOST_NAME,DNS:localhost,IP:$DPS_HOST_IP,IP:127.0.0.1
EOF
openssl x509 -req -in "$ldap_cfg/tls/server.csr" -CA "$ldap_cfg/tls/ca.crt" \
  -CAkey "$ldap_cfg/tls/ca.key" -CAcreateserial -sha256 -days 730 \
  -extfile "$ldap_cfg/tls/server.ext" -out "$ldap_cfg/tls/server.crt"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$ldap_cfg/dps-client.key"
openssl req -new -key "$ldap_cfg/dps-client.key" \
  -out "$ldap_cfg/dps-client.csr" -subj "/CN=dps-ldap-client"
cat > "$ldap_cfg/dps-client.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
EOF
openssl x509 -req -in "$ldap_cfg/dps-client.csr" -CA "$ldap_cfg/tls/ca.crt" \
  -CAkey "$ldap_cfg/tls/ca.key" -CAcreateserial -sha256 -days 730 \
  -extfile "$ldap_cfg/dps-client.ext" -out "$ldap_cfg/dps-client.crt"
openssl verify -CAfile "$ldap_cfg/tls/ca.crt" -purpose sslserver \
  -verify_ip "$DPS_HOST_IP" "$ldap_cfg/tls/server.crt"
openssl verify -CAfile "$ldap_cfg/tls/ca.crt" -purpose sslclient "$ldap_cfg/dps-client.crt"
chmod 600 "$ldap_cfg/tls/"*.key "$ldap_cfg/dps-client.key"
chmod 644 "$ldap_cfg/tls/"*.crt "$ldap_cfg/dps-client.crt"
~~~

预期两份证书验证 OK。Core 0.9 启动要求 CA、client cert、key 文件齐全；这不表示 OpenLDAP 强制用户以 mTLS 登录。用户认证仍由密码和组授权完成。

## 2. 用 slappasswd 从文件生成 SSHA

用自己刚构建的镜像，不用旧 image ID；密码不作为 -s 参数，也不打印。哈希同样视为私密文件。原生选项依据：[slappasswd -T / SSHA](https://manpages.debian.org/trixie/slapd/slappasswd.8.en.html)。

~~~bash
ldap_id=$(jq -r '.image_id' "$ldap_cfg/runtime-build.json")
for account in admin bind user noaccess; do
  docker run --rm --entrypoint /usr/sbin/slappasswd \
    -v "$ldap_cfg/$account.password:/password:ro" "$ldap_id" \
    -h '{SSHA}' -T /password > "$ldap_cfg/$account.hash"
  chmod 600 "$ldap_cfg/$account.hash"
done
~~~

## 3. 声明 ACL、用户、组与只读 bind

~~~bash
cat > "$ldap_cfg/slapd.conf" <<EOF
include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/nis.schema
include /etc/ldap/schema/inetorgperson.schema
pidfile /run/slapd/slapd.pid
argsfile /run/slapd/slapd.args
modulepath /usr/lib/ldap
moduleload back_mdb
TLSCACertificateFile /run/ldap-config/ca.crt
TLSCertificateFile /run/ldap-config/server.crt
TLSCertificateKeyFile /run/ldap-config/server.key
TLSProtocolMin 3.3
disallow bind_anon
require authc
security simple_bind=128
database mdb
maxsize 1073741824
suffix "dc=dps,dc=lab"
rootdn "cn=admin,dc=dps,dc=lab"
rootpw $(cat "$ldap_cfg/admin.hash")
directory /var/lib/ldap
index objectClass eq
index uid,cn eq
index member eq
access to attrs=userPassword
 by anonymous auth
 by self auth
 by * none
access to *
 by dn.exact="uid=dps-bind,ou=services,dc=dps,dc=lab" read
 by self read
 by * none
EOF
cat > "$ldap_cfg/bootstrap.ldif" <<EOF
dn: dc=dps,dc=lab
objectClass: top
objectClass: dcObject
objectClass: organization
dc: dps
o: DPS Independent Lab

dn: ou=users,dc=dps,dc=lab
objectClass: organizationalUnit
ou: users

dn: ou=groups,dc=dps,dc=lab
objectClass: organizationalUnit
ou: groups

dn: ou=services,dc=dps,dc=lab
objectClass: organizationalUnit
ou: services

dn: uid=dps-bind,ou=services,dc=dps,dc=lab
objectClass: account
objectClass: simpleSecurityObject
uid: dps-bind
userPassword: $(cat "$ldap_cfg/bind.hash")

dn: uid=dps-lab,ou=users,dc=dps,dc=lab
objectClass: inetOrgPerson
objectClass: posixAccount
uid: dps-lab
cn: DPS Lab Administrator
sn: Administrator
uidNumber: 10000
gidNumber: 10000
homeDirectory: /nonexistent
loginShell: /usr/sbin/nologin
userPassword: $(cat "$ldap_cfg/user.hash")

dn: uid=dps-noaccess,ou=users,dc=dps,dc=lab
objectClass: inetOrgPerson
objectClass: posixAccount
uid: dps-noaccess
cn: DPS Unprivileged Verification User
sn: Verification
uidNumber: 10002
gidNumber: 10000
homeDirectory: /nonexistent
loginShell: /usr/sbin/nologin
userPassword: $(cat "$ldap_cfg/noaccess.hash")

dn: cn=dcpower-users,ou=groups,dc=dps,dc=lab
objectClass: groupOfNames
cn: dcpower-users
member: uid=dps-lab,ou=users,dc=dps,dc=lab

EOF
chmod 600 "$ldap_cfg/slapd.conf" "$ldap_cfg/bootstrap.ldif"
~~~

8 条目录记录；dps-lab 是授权组成员，dps-noaccess 用于授权负例。bind 账号只能读普通目录属性，不能读取密码哈希或写目录；匿名不能 bind。admin rootdn 是维护账号，DPS 不使用其密码。

保存私密连接/用户信息供后续 Secret 与登录使用，程序仅把密码从文件转换到 JSON，不执行部署：

~~~bash
python3 - <<'PY'
import os,json
from pathlib import Path
c=Path(os.environ["DPS_RUNTIME_ROOT"])/"dps-install/config"; p=c/"ldap"
x={"endpoint":f'ldaps://{os.environ["DPS_HOST_IP"]}:{os.environ["DPS_LDAP_PORT"]}',
   "host":os.environ["DPS_HOST_IP"],"host_name":os.environ["DPS_HOST_NAME"],
   "port":int(os.environ["DPS_LDAP_PORT"]),"dns":"ldap.dps.lab",
   "base_dn":"dc=dps,dc=lab","user_base_dn":"ou=users,dc=dps,dc=lab",
   "group_base_dn":"ou=groups,dc=dps,dc=lab","admin_dn":"cn=admin,dc=dps,dc=lab",
   "username":"dps-lab","user_dn":"uid=dps-lab,ou=users,dc=dps,dc=lab",
   "bind_dn":"uid=dps-bind,ou=services,dc=dps,dc=lab",
   "authorization_group":"dcpower-users",
   "authorization_group_dn":"cn=dcpower-users,ou=groups,dc=dps,dc=lab",
   "noaccess_username":"dps-noaccess","noaccess_user_dn":"uid=dps-noaccess,ou=users,dc=dps,dc=lab",
   "admin_password":(p/"admin.password").read_text(),"bind_password":(p/"bind.password").read_text(),
   "password":(p/"user.password").read_text(),"noaccess_password":(p/"noaccess.password").read_text()}
x["user_password"]=x["password"]
x["allowgroup"]=x["authorization_group"]
(p/"credentials.json").write_text(json.dumps(x,indent=2)+"\n")
(c/"dps-access.json").write_text(json.dumps({"username":x["username"],"password":x["password"],
 "authentication":"ldap","authenticator":"ldap","role":"admin","ldap_dn":x["user_dn"]},indent=2)+"\n")
for q in [p/"credentials.json",c/"dps-access.json"]: q.chmod(0o600)
PY
~~~

## 4. 启动 LDAPS，检查真实身份

~~~bash
cat > "$ldap_cfg/compose.yaml" <<EOF
services:
  openldap:
    image: "$ldap_id"
    pull_policy: never
    container_name: $DPS_LDAP_CONTAINER
    restart: unless-stopped
    read_only: true
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    cap_add: [CHOWN, FOWNER, SETUID, SETGID, DAC_OVERRIDE]
    ports: ["$DPS_HOST_IP:$DPS_LDAP_PORT:1636"]
    volumes:
      - $ldap_cfg:/ldap/config:ro
      - $ldap_data:/var/lib/ldap
    tmpfs:
      - /run:rw,nosuid,nodev,mode=755
      - /tmp:rw,nosuid,nodev,mode=1777
    environment:
      LDAPTLS_CACERT: /ldap/config/tls/ca.crt
      LDAPTLS_REQCERT: demand
    healthcheck:
      test: [CMD, ldapwhoami, -x, -H, "ldaps://127.0.0.1:1636", -D, "uid=dps-bind,ou=services,dc=dps,dc=lab", -y, /ldap/config/bind.password]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 10s
    logging:
      driver: json-file
      options: {max-size: "10m", max-file: "3"}
EOF
docker compose -p "$DPS_LDAP_PROJECT" -f "$ldap_cfg/compose.yaml" config --quiet
docker compose -p "$DPS_LDAP_PROJECT" -f "$ldap_cfg/compose.yaml" up -d --wait
docker compose -p "$DPS_LDAP_PROJECT" -f "$ldap_cfg/compose.yaml" ps
LDAPTLS_CACERT="$ldap_cfg/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapwhoami -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-lab,ou=users,dc=dps,dc=lab" -y "$ldap_cfg/user.password"
LDAPTLS_CACERT="$ldap_cfg/tls/ca.crt" LDAPTLS_REQCERT=demand \
  ldapsearch -LLL -x -H "ldaps://$DPS_HOST_IP:$DPS_LDAP_PORT" \
  -D "uid=dps-bind,ou=services,dc=dps,dc=lab" -y "$ldap_cfg/bind.password" \
  -b "ou=groups,dc=dps,dc=lab" '(cn=dcpower-users)' cn member
~~~

预期 healthy；ldapwhoami 返回 dps-lab DN，查询组包含其完整 member DN。容器 entrypoint 首次仅对空目录执行 slapadd，随后留下 .initialized；重启复用 data.mdb。实际 slapd UID 10001，不作为宿主机服务运行。

## 5. 备份与后续 DPS 认证

~~~bash
ldap_backups="$DPS_RUNTIME_ROOT/dps-install/data/ldap-backups"
mkdir -p "$ldap_backups"
ldap_backup="$ldap_backups/ldap-$(date -u +%Y%m%dT%H%M%SZ).ldif"
docker exec "$DPS_LDAP_CONTAINER" slapcat -f /run/ldap-config/slapd.conf \
  > "$ldap_backup"
chmod 600 "$ldap_backup"
test "$(awk '/^dn: / {n++} END {print n}' "$ldap_backup")" = 8
~~~

slapcat 可对 MDB 在线导出；恢复用 slapadd 时需停止 LDAP 并导入新的空目录，保留旧数据再切换，不向运行 data.mdb 覆盖。依据：[OpenLDAP 维护](https://www.openldap.org/doc/admin26/maintenance.html)。DPS 后续挂载三份 LDAP Secret，authenticatorType=ldap、groupRoleMapping=dcpower-users=admin、auth_required_groups=dcpower-users、defaultRole 为空。真实组外用户可获得无角色 token，但受保护 API/RPC 拒绝；不能写成“组外账号无法登录”。继续 [DPS 手工安装](manual-install.md)。
