from pysnmp.hlapi import *

community_string = 'public'
ip_address_host = '192.168.1.30'
port_snmp = 161
on = Integer(1)
off = Integer(0)
# словарь можно заменить на переменные
OID = {
    'ALARM-3': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.4',
    'ALARM-2': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.3',
    'ALARM-1': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.2',
    'ALARM-4': '.1.3.6.1.4.1.40418.2.6.2.2.1.3.1.5',
}


def set_cmd(key, value, port=161, engine=SnmpEngine(), context=ContextData()):
    return (setCmd(
        engine,
        CommunityData(community_string),
        UdpTransportTarget((ip_address_host, port_snmp)),
        context,
        ObjectType(ObjectIdentity(key), value)
    ))


# изменение состояния
def snmp_set(key, value):
    errorIndication, errorStatus, errorIndex, varBinds = next(set_cmd(key, value))
    for name, val in varBinds:
        return val.prettyPrint()


def get_cmd(key, port=161, engine=SnmpEngine(), context=ContextData()):
    return (getCmd(
        engine,
        CommunityData(community_string),
        UdpTransportTarget((ip_address_host, port_snmp)),
        context,
        ObjectType(ObjectIdentity(key))
    ))


def snmp_get(key):
    """получение состояния"""
    errorIndication, errorStatus, errorIndex, varBinds = next(get_cmd(key))
    for name, val in varBinds:
        return val.prettyPrint()
