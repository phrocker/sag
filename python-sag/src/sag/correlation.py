from __future__ import annotations

import itertools
import time
from typing import Optional

from sag.model import Header, Message

_message_id_counter = itertools.count(1)


class CorrelationEngine:
    def __init__(self, agent_id: str):
        self._agent_id = agent_id
        self._correlation_map: dict[str, str] = {}

    def record_incoming(self, message: Message) -> None:
        if message is not None and message.header is not None:
            message_id = message.header.message_id
            if message_id is not None:
                self._correlation_map["last_received"] = message_id

    def create_response_header(self, source: str, destination: str) -> Header:
        message_id = self.generate_message_id()
        timestamp = int(time.time())
        correlation = self._correlation_map.get("last_received")
        return Header(version=1, message_id=message_id, source=source, destination=destination, timestamp=timestamp, correlation=correlation)

    def create_header_with_correlation(self, source: str, destination: str, correlation_id: str) -> Header:
        message_id = self.generate_message_id()
        timestamp = int(time.time())
        return Header(version=1, message_id=message_id, source=source, destination=destination, timestamp=timestamp, correlation=correlation_id)

    def create_header_in_response_to(self, source: str, destination: str, in_response_to: Message) -> Header:
        message_id = self.generate_message_id()
        timestamp = int(time.time())
        correlation = None
        if in_response_to is not None and in_response_to.header is not None:
            correlation = in_response_to.header.message_id
        return Header(version=1, message_id=message_id, source=source, destination=destination, timestamp=timestamp, correlation=correlation)

    def generate_message_id(self) -> str:
        counter = next(_message_id_counter)
        return f"{self._agent_id}-{counter}"

    @staticmethod
    def trace_thread(messages: list[Message], start_message_id: str) -> list[Message]:
        message_map: dict[str, Message] = {}
        for msg in messages:
            if msg.header is not None and msg.header.message_id is not None:
                message_map[msg.header.message_id] = msg

        thread: list[Message] = []
        current_id: Optional[str] = start_message_id
        visited: set[str] = set()

        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            msg = message_map.get(current_id)
            if msg is None:
                break
            thread.append(msg)
            if msg.header.correlation is not None:
                current_id = msg.header.correlation
            else:
                break

        thread.reverse()
        return thread

    @staticmethod
    def find_responses(messages: list[Message], message_id: str) -> list[Message]:
        responses: list[Message] = []
        for msg in messages:
            if msg.header is not None and msg.header.correlation is not None:
                if message_id == msg.header.correlation:
                    responses.append(msg)
        return responses

    @staticmethod
    def build_conversation_tree(messages: list[Message]) -> dict[str, list[str]]:
        tree: dict[str, list[str]] = {}
        for msg in messages:
            if msg.header is not None and msg.header.message_id is not None:
                msg_id = msg.header.message_id
                if msg_id not in tree:
                    tree[msg_id] = []
                correlation_id = msg.header.correlation
                if correlation_id is not None:
                    if correlation_id not in tree:
                        tree[correlation_id] = []
                    tree[correlation_id].append(msg_id)
        return tree

    def clear(self) -> None:
        self._correlation_map.clear()
