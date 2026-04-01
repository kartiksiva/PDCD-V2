"""Service Bus helpers for orchestration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict, Optional

from azure.servicebus import ServiceBusClient, ServiceBusMessage

DEFAULT_MAX_RETRIES = 3


@dataclass(frozen=True)
class QueueConfig:
    extracting: str
    processing: str
    reviewing: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_queue_config() -> QueueConfig:
    return QueueConfig(
        extracting=os.environ.get("AZURE_SERVICE_BUS_QUEUE_EXTRACTING", "extracting"),
        processing=os.environ.get("AZURE_SERVICE_BUS_QUEUE_PROCESSING", "processing"),
        reviewing=os.environ.get("AZURE_SERVICE_BUS_QUEUE_REVIEWING", "reviewing"),
    )


def _connection_string() -> Optional[str]:
    return os.environ.get("AZURE_SERVICE_BUS_CONNECTION_STRING")


def _payload_hash(message: Dict[str, Any]) -> str:
    payload = json.dumps(message, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def build_message(job_id: str, phase: str, attempt: int, *, requested_by: str, trace_id: str) -> Dict[str, Any]:
    message = {
        "job_id": job_id,
        "phase": phase,
        "attempt": attempt,
        "requested_by": requested_by,
        "trace_id": trace_id,
    }
    message["payload_hash"] = _payload_hash(message)
    return message


class ServiceBusOrchestrator:
    def __init__(self) -> None:
        self.connection_string = _connection_string()
        self.queue_config = _get_queue_config()

    @property
    def enabled(self) -> bool:
        return bool(self.connection_string)

    def enqueue(self, phase: str, message: Dict[str, Any], *, delay_seconds: int = 0) -> None:
        if not self.connection_string:
            return
        queue_name = getattr(self.queue_config, phase)
        bus_message = ServiceBusMessage(json.dumps(message, separators=(",", ":")))
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            sender = client.get_queue_sender(queue_name)
            with sender:
                if delay_seconds > 0:
                    schedule_time = _utc_now() + timedelta(seconds=delay_seconds)
                    sender.schedule_messages(bus_message, schedule_time)
                else:
                    sender.send_messages(bus_message)

    def receive(self, phase: str, *, max_wait_time: int = 5):
        if not self.connection_string:
            return None
        queue_name = getattr(self.queue_config, phase)
        client = ServiceBusClient.from_connection_string(self.connection_string)
        return client.get_queue_receiver(queue_name, max_wait_time=max_wait_time)


def max_retries() -> int:
    value = os.environ.get("PFCD_MAX_RETRIES")
    if value and value.isdigit():
        return int(value)
    return DEFAULT_MAX_RETRIES
