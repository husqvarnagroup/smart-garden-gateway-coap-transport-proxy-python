# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import socket

LEMONBEAT_TCLASS_ENCRYPTED = 0x1c

logger = logging.getLogger('coap-transport-proxy')

orig_socket = socket.socket


class PatchedSocket(orig_socket):
    ignore_tclass = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.family == socket.AF_INET6 and self.type == socket.SOCK_DGRAM:
            # Set traffic class for all IPv6 UDP packets, UDP is only used in the CoAP interface.
            # Connections to the Internet are all TCP and thus are unchanged.
            # NOTE: Other things running in the same Python interpreter are also affected.
            self.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_TCLASS, LEMONBEAT_TCLASS_ENCRYPTED)
            # Receive traffic class on incoming packets.
            self.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_RECVTCLASS, 1)

    def recvmsg(self, *args, **kwargs):
        if len(args) > 2:
            flags = args[2]
        else:
            flags = kwargs.get('flags')

        data, ancdata, msg_flags, address = super().recvmsg(*args, **kwargs)
        if flags is not None and flags & socket.MSG_ERRQUEUE:
            # drain queue but ignore errors
            logger.warning("Received ICMP error. Ignoring.")
            raise BlockingIOError
        for i, (cmsg_level, cmsg_type, cmsg_data) in enumerate(ancdata):
            if cmsg_level == socket.IPPROTO_IPV6 and cmsg_type == socket.IPV6_TCLASS:
                del ancdata[i]
                if cmsg_data[0] & LEMONBEAT_TCLASS_ENCRYPTED == LEMONBEAT_TCLASS_ENCRYPTED:
                    # packet was sent encrypted
                    break
        else:
            # packet was not encrypted
            if not self.ignore_tclass:
                logger.warning("Received unencrypted packet. Ignoring.")
                raise BlockingIOError
        return data, ancdata, msg_flags, address


class PatchedSocketIgnoringTClass(PatchedSocket):
    ignore_tclass = True


def apply(ignore_tclass=False):
    if not ignore_tclass:
        socket.socket = PatchedSocket
    else:
        logger.warning("Ignoring traffic class in all incoming data (use for development only!)")
        socket.socket = PatchedSocketIgnoringTClass
