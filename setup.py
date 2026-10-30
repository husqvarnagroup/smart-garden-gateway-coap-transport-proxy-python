# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from setuptools import setup

# NOTE: arguments to setup() can be removed as soon as setuptools version >= 61.0.0 are being used.
# Configuration is then solely in pyproject.toml.
setup(
    name="coap_transport_proxy",
    version='0.2.0',
    description="A custom proxy server allowing clients to open TCP sockets with optional TLS encryption using the CoAP protocol.",
    python_requires=">=3.8",
    install_requires=[
        'aiocoap~=0.4.5',
    ],
    packages=["coap_transport_proxy"],
    entry_points={
        'console_scripts': [
            'coap-transport-proxy = coap_transport_proxy.server:main',
        ]
    }
)
