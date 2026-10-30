# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import socket
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Union


def mangle_source_address(address):
    """Map link-local source address to unique-local (fc00::6:<mac>)
    so that the gateway dongle sends the reply correctly.
    Only perform mangle if scope id is ppp0, ppp1, etc.
    """
    # we can only determine interface if scope id is set
    if len(address) != 4 or address[3] == 0:
        return address

    # only mangle link-local IPv6 addresses
    addr: Union[IPv4Address, IPv6Address] = ip_address(address[0])
    if addr.version != 6 or not addr.is_link_local:
        return address

    # only mangle from ppp0, ppp1, etc.
    ni = socket.getnameinfo(address, socket.NI_NUMERICHOST | socket.NI_NUMERICSERV)
    if not re.match(r'.*%ppp\d+$', ni[0]):
        return address

    ap = addr.packed
    new_addr = ip_address(b'\xfc\0\0\0\0\0\0\0\0\x06' + ap[8:11] + ap[13:]).compressed

    # set scope id to 0
    return new_addr, *address[1:3], 0
