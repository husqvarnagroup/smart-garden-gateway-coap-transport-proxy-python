# CoAP Transport Proxy

> This code is not used in production anymore. We provide it only for
> reference.

## Development Setup

### Python Version

Best you use the same Python version as on the Gateway, which currently
is Python 3.8. Python 3.9 should work, too, but Python 3.11 currently
doesn't work.

### Virtualenv Creation and Activation

Create a virtualenv using your custom Python version:

```bash
/path/to/your/custom/python3.8/bin/python3 -m venv venv
```

Activate the virtualenv in your current shell:

```bash
. venv/bin/activate
```

### Install Project and Dependencies

Install the project in editable mode together will all dependencies
including test dependencies in the virtualenv:

```bash
pip install -e .[test]
```

### Run Tests

Run all tests in the virtualenv:

```bash
pytest
```

### Run CoAP Transport Proxy Server

After installation in the virtualenv:

```bash
coap-transport-proxy
```

## Run on a Gateway

If you run a GW build >= 7.6.1 then you can install the transport proxy via opkg:

```bash
opkg update && opkg install python3-coap-transport-proxy
```

Check the status with:

```bash
systemctl status coap-transport-proxy
```

To run a custom version, copy all files to the Gateway:

```bash
git archive --format=tar --prefix=coap-transport-proxy/ HEAD | ssh root@gateway tar xv -C /home/root
```

Install depedencies on the Gateway:

```bash
opkg update
opkg install python3-aiocoap
```

Run CoAP transport proxy on the Gateway:

```bash
cd /home/root/coap-transport-proxy
PYTHONPATH=$(pwd) python3 coap_transport_proxy/server.py
```
