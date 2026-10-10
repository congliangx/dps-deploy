#!/bin/sh
set -eu
umask 077
mkdir -p /run/slapd /run/ldap-config /var/lib/ldap
# Read the private host config as root, then run slapd as an unprivileged user.
cp /ldap/config/slapd.conf /run/ldap-config/slapd.conf
cp /ldap/config/tls/server.crt /run/ldap-config/server.crt
cp /ldap/config/tls/server.key /run/ldap-config/server.key
cp /ldap/config/tls/ca.crt /run/ldap-config/ca.crt
chown -R ldapdaemon:ldapdaemon /run/slapd /run/ldap-config /var/lib/ldap
chmod 700 /run/slapd /run/ldap-config /var/lib/ldap
chmod 600 /run/ldap-config/server.key /run/ldap-config/slapd.conf
slaptest -u -f /run/ldap-config/slapd.conf
# Initialize only a genuinely empty database; incomplete state must be investigated.
if [ ! -f /var/lib/ldap/data.mdb ]; then
    if [ -f /var/lib/ldap/.initialized ]; then
        echo 'Initialized LDAP data file missing; refusing to reseed.' >&2
        exit 1
    fi
    if [ -n "$(find /var/lib/ldap -mindepth 1 -maxdepth 1 -type f -print -quit)" ]; then
        echo 'Unexpected files in new LDAP database; refusing to reseed.' >&2
        exit 1
    fi
    slapadd -f /run/ldap-config/slapd.conf -l /ldap/config/bootstrap.ldif
    touch /var/lib/ldap/.initialized
    chown -R ldapdaemon:ldapdaemon /var/lib/ldap
elif [ ! -f /var/lib/ldap/.initialized ]; then
    echo 'LDAP database exists without initialization marker; inspect before starting.' >&2
    exit 1
fi
exec slapd -f /run/ldap-config/slapd.conf -h 'ldaps://0.0.0.0:1636/' -u ldapdaemon -g ldapdaemon -d 256
