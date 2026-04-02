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
            logger.debug("Service Bus not configured; skipping enqueue for phase %s", phase)
            return
        queue_name = getattr(self.queue_config, phase)
        bus_message = ServiceBusMessage(json.dumps(message, separators=(",", ":")))
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            sender = client.get_queue_sender(queue_name)
            with sender:
                if delay_seconds > 0:
                    schedule_time = _utc_now() + timedelta(seconds=delay_seconds)
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
