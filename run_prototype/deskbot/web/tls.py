"""
HTTPS for the dashboard, so phones and laptops can use their microphone.

Browsers only allow getUserMedia (microphone) on a "secure context": https:// or http://localhost.
http://<pi-ip>:8000 is neither, so the dashboard ALSO listens on https://<pi-ip>:8443 with a
self-signed certificate. The first visit shows a certificate warning (Advanced -> Proceed); after that
the page is a secure context and the mic works. Plain HTTP on :8000 keeps working for everything else.

The certificate is made once with the `openssl` command (preinstalled on Raspberry Pi OS and in Git
for Windows) and kept in data/tls/. It is regenerated when the machine's names/IPs change (for example
the hotspot address 10.42.0.1 appears), so the certificate always names the address you browse to.
"""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path


def local_names(extra_ips=()):
    host = socket.gethostname()
    names = sorted({host, f"{host}.local", "localhost"})
    ips = {"127.0.0.1", "10.42.0.1"} | set(extra_ips)   # 10.42.0.1 = NetworkManager hotspot address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return names, sorted(ips)


def ensure_cert(directory: Path):
    """(cert_path, key_path), creating/refreshing a self-signed cert. Raises RuntimeError without openssl."""
    directory.mkdir(parents=True, exist_ok=True)
    cert, key, meta = directory / "cert.pem", directory / "key.pem", directory / "names.json"
    names, ips = local_names()
    want = {"names": names, "ips": ips}
    if cert.exists() and key.exists() and meta.exists():
        try:
            have = json.loads(meta.read_text())
            if set(want["names"]) <= set(have["names"]) and set(want["ips"]) <= set(have["ips"]):
                return cert, key
            want = {"names": sorted(set(have["names"]) | set(names)), "ips": sorted(set(have["ips"]) | set(ips))}
        except (OSError, ValueError, KeyError):
            pass
    exe = shutil.which("openssl")
    if not exe:
        raise RuntimeError("openssl not found (sudo apt install openssl)")
    san = ",".join([f"DNS:{n}" for n in want["names"]] + [f"IP:{i}" for i in want["ips"]])
    r = subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "825",
                        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=deskbot",
                        "-addext", f"subjectAltName={san}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("openssl failed: " + r.stderr.strip()[-200:])
    meta.write_text(json.dumps(want))
    try:
        key.chmod(0o600)
    except OSError:
        pass
    return cert, key


class _QuietTLSServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        # browsers probing the self-signed cert, plain-HTTP clients, dropped connections: not errors
        if isinstance(exc, (ssl.SSLError, ConnectionError, TimeoutError, OSError)):
            return
        super().handle_error(request, client_address)


def serve_https(host, port, handler_cls, cert, key):
    """Start an HTTPS ThreadingHTTPServer on a daemon thread. Returns the server (call .shutdown())."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert), str(key))
    server = _QuietTLSServer((host, port), handler_cls)
    server.daemon_threads = True
    # handshake lazily in the request thread: a slow or plain-HTTP client can't block accept()
    server.socket = ctx.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    threading.Thread(target=server.serve_forever, name="https", daemon=True).start()
    return server
