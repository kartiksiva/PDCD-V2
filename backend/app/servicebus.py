"""Service Bus helpers for orchestration."""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict, Iterator, Optional

from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusReceiver

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3


@dataclass(frozen=True)
class QueueConfig:
    extracting: str
    processing: str
    reviewing: str


def _utc_now_dt() -> datetime:
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
        self._enqueue_client: Optional[ServiceBusClient] = None
        self._senders: Dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.connection_string)

    def _get_enqueue_client(self) -> Optional[ServiceBusClient]:
        if not self.connection_string:
            return None
        if self._enqueue_client is None:
            self._enqueue_client = ServiceBusClient.from_connection_string(self.connection_string)
        return self._enqueue_client

    def _get_sender(self, queue_name: str):
        sender = self._senders.get(queue_name)
        if sender is not None:
            return sender
        client = self._get_enqueue_client()
        if client is None:
            return None
        sender = client.get_queue_sender(queue_name)
        sender.__enter__()
        self._senders[queue_name] = sender
        return sender

    def close(self) -> None:
        for sender in self._senders.values():
            try:
                sender.__exit__(None, None, None)
            except Exception:
                pass
        self._senders.clear()
        if self._enqueue_client is not None:
            try:
                self._enqueue_client.close()
            except Exception:
                pass
            self._enqueue_client = None

    def enqueue(self, phase: str, message: Dict[str, Any], *, delay_seconds: int = 0) -> None:
        if not self.connection_string:
            logger.debug("Service Bus not configured; skipping enqueue for phase %s", phase)
            return
        queue_name = getattr(self.queue_config, phase)
        bus_message = ServiceBusMessage(json.dumps(message, separators=(",", ":")))
        sender = self._get_sender(queue_name)
        if sender is None:
            return
        if delay_seconds > 0:
            schedule_time = _utc_now_dt() + timedelta(seconds=delay_seconds)
            sender.schedule_messages(bus_message, schedule_time)
            logger.info("Scheduled message for phase %s in %ds", phase, delay_seconds)
        else:
            sender.send_messages(bus_message)
            logger.info("Enqueued message for phase %s job_id=%s", phase, message.get("job_id"))

    @contextmanager
    def receive(self, phase: str, *, max_wait_time: int = 5) -> Iterator[Optional[ServiceBusReceiver]]:
        if not self.connection_string:
            yield None
            return
        queue_name = getattr(self.queue_config, phase)
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            with client.get_queue_receiver(queue_name, max_wait_time=max_wait_time) as receiver:
                logger.debug("Opened Service Bus receiver for queue %s", queue_name)
                yield receiver
        logger.debug("Closed Service Bus receiver for queue %s", queue_name)


def max_retries() -> int:
    value = os.environ.get("PFCD_MAX_RETRIES")
    if value and value.isdigit():
        return int(value)
    return DEFAULT_MAX_RETRIES
