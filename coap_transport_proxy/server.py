#!/usr/bin/env python3

# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prototype implementation of the GARDENA cloud connection proxy."""

import argparse
import asyncio
import json
import logging
import os
import ssl
from asyncio import StreamReader, StreamWriter
from typing import Optional

import aiocoap
import aiocoap.resource as resource

from coap_transport_proxy import socket_patch

SERVER_PORT = 20024  # See https://confluence-husqvarna.riada.se/x/grGqC
NET_HEADER_SIZE_RESERVED = 64  # In addition to the payload, these bytes must also fit into a SharedNetBuffer
MAX_CBT11_NET_BUFFER = 1024  # Network buffer size of CBT11
READ_SIZE = MAX_CBT11_NET_BUFFER - NET_HEADER_SIZE_RESERVED  # Max is 1452 (PPP0 interface max is 1500 including header)
MAX_NUMBER_OF_SOCKETS = 256

CANCELLED = object()

logger = logging.getLogger('coap-transport-proxy')


# TODO:
#   * cleanup stale sockets after some time


class SocketResource(resource.Resource):
    def __init__(self, root, client, client_uri_path, id_, host, port, enable_tls, verify_certificate):
        self._root = root
        self.client = client
        self._client_uri_path = client_uri_path
        self.id = id_
        self.host = host
        self.port = port
        self.enable_tls = enable_tls
        self.verify_certificate = verify_certificate

        self._reader: Optional[StreamReader] = None
        self._writer: Optional[StreamWriter] = None
        self._task = asyncio.get_event_loop().create_task(self._connect_and_read())
        self._closing_notified = False

        super().__init__()

    async def render_post(self, request: aiocoap.Message):
        """Send data
        """
        if self.state == "CONNECTING":
            return aiocoap.Message(code=aiocoap.Code.METHOD_NOT_ALLOWED)
        elif self.state != "CONNECTED":
            return aiocoap.Message(code=aiocoap.Code.BAD_GATEWAY)
        length = len(request.payload)
        logger.debug("Sending %d Bytes to %s:%d", length, self.host, self.port)
        self._writer.write(request.payload)
        # FLow control:
        # Drain and then respond to the post. Empty ACKs are automatically sent after 100 ms without response.
        await self._writer.drain()
        logger.debug("Sent %d Bytes to %s:%d", length, self.host, self.port)
        return aiocoap.Message(code=aiocoap.Code.CHANGED)

    async def render_delete(self, request: aiocoap.Message):
        self.delete()
        return aiocoap.Message(code=aiocoap.Code.DELETED)

    def delete(self):
        self._task.cancel()
        self.close()
        asyncio.get_event_loop().create_task(self.notify_closed())
        self._root.remove_socket(self)

    def close(self):
        if self._writer is not None:
            self._writer.close()

    async def notify_data(self, payload=b''):
        async def handle_error():
            logger.debug("Sending data to client %s failed.", self.client_uri)
            self.close()
            await self.notify_closed()

        message = aiocoap.Message(code=aiocoap.Code.POST, payload=payload, uri=self.client_uri)
        # noinspection PyBroadException
        try:
            response = await self._root._protocol.request(message).response
        except Exception:
            await handle_error()
            return False
        if response.code != aiocoap.Code.CHANGED:
            await handle_error()
            return False
        return True

    async def notify_closed(self):
        if self._closing_notified:
            return
        self._closing_notified = True
        message = aiocoap.Message(code=aiocoap.Code.DELETE, uri=self.client_uri)
        # noinspection PyBroadException
        try:
            await self._root._protocol.request(message).response
        except Exception:
            # ignore delivery failure
            pass

    async def _connect_and_read(self):
        ssl_context = self.enable_tls
        if self.enable_tls and not self.verify_certificate:
            ssl_context = ssl.SSLContext()
            ssl_context.verify_mode = ssl.CERT_NONE
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port, ssl=ssl_context)
        except Exception as e:
            logger.debug("Connection to %s:%d failed", self.host, self.port, exc_info=e)
            self.close()
            await self.notify_closed()
            return
        logger.debug("Connection to %s:%d succeeded", self.host, self.port)
        # send empty message to signal connection is established
        if not await self.notify_data():
            return

        while True:
            # FLow control:
            # Only read next chunk when client responded to the previous post.
            data = await self._reader.read(READ_SIZE)
            if not data:
                if self._writer.is_closing():
                    break
                logger.debug("Connection to %s:%d closed", self.host, self.port)
                self.close()
                await self.notify_closed()
                break
            logger.debug("Read %d Bytes from %s:%d", len(data), self.host, self.port)
            if not await self.notify_data(payload=data):
                break

    @property
    def state(self):
        if self._reader is None:
            if not self._task.done():
                return "CONNECTING"
            else:
                return "FAILED"
        elif self._reader.at_eof() or self._writer.transport.is_closing():
            return "CLOSED"
        else:
            return "CONNECTED"

    @property
    def client_uri(self):
        return 'coap://' + self.client + self._client_uri_path


class RootResource(resource.Resource):
    def __init__(self, protocol):
        self._protocol = protocol
        self._sockets: {str: {str: SocketResource}} = {}
        super().__init__()

    async def render_get(self, request: aiocoap.Message):
        """Query overall state

        response:
        * always ok
        * network state of Gateway, to be implemented and further defined.
        """
        payload = {
            'is_network_connected': True,
            'sockets': [{
                "client_uri": s.client_uri,
                "id": s.id,
                "host": s.host,
                "port": s.port,
                "state": s.state,
            } for s in self._sockets.get(request.remote.hostinfo, {}).values()]
        }
        return aiocoap.Message(payload=json.dumps(payload).encode())

    async def render_post(self, request: aiocoap.Message):
        """Create socket

        request parameters:
        * host name : string
        * port : u16
        * tls_enabled : bool
        * certificate_validation_enabled : bool

        response:
        * response code created if successful, error otherwise
        * location header: path of created socket on success
        """
        payload = json.loads(request.payload)
        id_ = self._get_next_free_id(request.remote.hostinfo)
        if id_ is None:
            return aiocoap.Message(code=aiocoap.Code.SERVICE_UNAVAILABLE)
        enable_tls = bool(payload.get("t", 0))
        verify_certificate = bool(payload.get("v", enable_tls))
        client_uri_path = payload["c"]
        if not client_uri_path.startswith("/"):
            client_uri_path = "/" + client_uri_path
        self._sockets.setdefault(request.remote.hostinfo, {})[id_] = SocketResource(
            self, request.remote.hostinfo, client_uri_path, id_, payload["h"], int(payload["p"]), enable_tls,
            verify_certificate)
        return aiocoap.Message(code=aiocoap.Code.CREATED, location_path=(id_,))

    async def render_delete(self, request: aiocoap.Message):
        """Delete all resources associated with the requesting client

        response:
        * always response code deleted
        """
        # TODO: prevent possible race conditions?
        ids = [id_ for id_ in self._sockets.get(request.remote.hostinfo, {})]
        for id_ in ids:
            self._sockets[request.remote.hostinfo][id_].delete()
        return aiocoap.Message(code=aiocoap.Code.DELETED)

    def remove_socket(self, socket):
        if self._sockets.get(socket.client, {}).get(socket.id) is socket:
            logger.debug("Removing connection to %s:%d", socket.host, socket.port)
            del self._sockets[socket.client][socket.id]
            if not len(self._sockets[socket.client]):
                del self._sockets[socket.client]

    def get_resource(self, request: aiocoap.Message):
        if request.opt.uri_path in [(), ("",)] and request.opt.uri_query == ():
            return self
        if len(request.opt.uri_path) != 1 or request.opt.uri_query != ():
            return None
        return self._sockets.get(request.remote.hostinfo, {}).get(request.opt.uri_path[0])

    def _get_next_free_id(self, client):
        sockets = self._sockets.get(client, {})
        for i in range(MAX_NUMBER_OF_SOCKETS):
            id_ = str(i)
            if id_ not in sockets:
                return id_
        return None


class SocketSite(resource.Resource, resource.PathCapable):
    def __init__(self, protocol):
        self._root = RootResource(protocol)
        super().__init__()

    async def needs_blockwise_assembly(self, request: aiocoap.Message):
        return True

    async def render(self, request: aiocoap.Message):
        rsrc = self._root.get_resource(request)
        if rsrc is None:
            return aiocoap.Message(code=aiocoap.Code.NOT_FOUND)
        return await rsrc.render(request)


async def main_async(ignore_tclass=False):
    # error when accidentally running the server twice
    os.environ['AIOCOAP_REUSE_PORT'] = '0'

    socket_patch.apply(ignore_tclass=ignore_tclass)

    protocol = await aiocoap.Context.create_server_context(None, bind=('::', SERVER_PORT), transports=['udp6'])
    # Resource tree creation
    protocol.serversite = SocketSite(protocol)

    # Run forever
    await asyncio.get_running_loop().create_future()


def main():
    logging.basicConfig()
    loglevel = os.environ.get('LOGLEVEL')
    if loglevel is not None:
        logger.setLevel(level=loglevel.upper())
        logging.getLogger('coap-server').setLevel(level=loglevel.upper())

    parser = argparse.ArgumentParser()
    parser.add_argument('--ignore-tclass', action='store_true')
    args = parser.parse_args()

    asyncio.run(main_async(ignore_tclass=args.ignore_tclass))


if __name__ == '__main__':
    main()
