"""WebSocket transport for SAG messages."""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.model import Message
from sag.exceptions import SAGParseException


class WebSocketTransport:
    """Serialize/deserialize SAG messages over WebSocket text frames."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self._host = host
        self._port = port
        self._server = None
        self._connections: set = set()
        self._on_message: Optional[Callable] = None

    def on_message(self, callback: Callable[[Message, str], None]):
        self._on_message = callback

    async def start_server(self):
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets package not installed. Run: pip install websockets")

        async def handler(websocket):
            self._connections.add(websocket)
            try:
                async for raw in websocket:
                    try:
                        message = SAGMessageParser.parse(raw)
                        if self._on_message:
                            self._on_message(message, raw)
                    except SAGParseException as e:
                        await websocket.send(f'ERR PARSE_ERROR "{e}"')
            finally:
                self._connections.discard(websocket)

        self._server = await websockets.serve(handler, self._host, self._port)

    async def send(self, message: Message):
        raw = MessageMinifier.to_minified_string(message)
        for ws in self._connections:
            await ws.send(raw)

    async def send_raw(self, raw: str):
        for ws in self._connections:
            await ws.send(raw)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @staticmethod
    def serialize(message: Message) -> str:
        return MessageMinifier.to_minified_string(message)

    @staticmethod
    def deserialize(raw: str) -> Message:
        return SAGMessageParser.parse(raw)
