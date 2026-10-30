# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import socket
from unittest.mock import patch

from coap_transport_proxy.lemonbeat_quirks import mangle_source_address


def mock_getnameinfo(address, flags):
    assert flags == socket.NI_NUMERICHOST | socket.NI_NUMERICSERV
    if len(address) == 2:
        return address
    assert len(address) == 4
    scope_id_suffix = ""
    if address[3] == 3:
        scope_id_suffix = "%ppp0"
    if address[3] == 4:
        scope_id_suffix = "%ppp1"
    return address[0] + scope_id_suffix, address[1]


def test_mangle_source_address():
    with patch("socket.getnameinfo", mock_getnameinfo):
        assert mangle_source_address(("192.0.2.5", 42)) == ("192.0.2.5", 42)
        assert mangle_source_address(("::1", 80, 1, 2)) == ("::1", 80, 1, 2)
        assert mangle_source_address(("2001:db8::42", 443, 3, 3)) == ("2001:db8::42", 443, 3, 3)

        assert mangle_source_address(("fe80::0201:23ff:fe45:6789", 8080, 5, 3)) == ("fc00::6:201:2345:6789", 8080, 5, 0)
        assert mangle_source_address(("fe80::0201:23ff:fe45:6789", 1234, 0, 4)) == ("fc00::6:201:2345:6789", 1234, 0, 0)
