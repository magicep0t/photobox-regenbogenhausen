"""Entry point: ``python3 -m photobox``."""

from __future__ import annotations

import logging
import socket

import uvicorn

from .app import create_app
from .config import load_config

log = logging.getLogger("photobox")

IP_FREEBIND = getattr(socket, "IP_FREEBIND", 15)  # Linux


def listen_socket(host: str, port: int, freebind: bool = False) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if freebind:
        # bind even if the address doesn't exist yet (hotspot stick not plugged
        # in or not up yet); connections arrive as soon as it does
        sock.setsockopt(socket.SOL_IP, IP_FREEBIND, 1)
    sock.bind((host, port))
    return sock


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    sockets = [listen_socket(cfg.host, cfg.port)]
    log.info("Touch UI on http://%s:%s", cfg.host, cfg.port)
    if cfg.hotspot.enabled:
        try:
            sockets.append(listen_socket(cfg.hotspot.address, cfg.hotspot.port, freebind=True))
            log.info("Phone downloads on http://%s:%s", cfg.hotspot.address, cfg.hotspot.port)
        except OSError as err:
            log.error("Cannot listen on the hotspot address, phone downloads disabled: %s", err)

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(cfg),
            log_level="info",
            # the MJPEG stream never ends by itself; don't wait for it on shutdown
            timeout_graceful_shutdown=3,
        )
    )
    server.run(sockets=sockets)


if __name__ == "__main__":
    main()
