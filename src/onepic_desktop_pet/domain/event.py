"""端云同步语义事件领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CloudEvent:
    """桌面端、小程序和云端之间同步的语义事件。"""

    event_id: str
    event_type: str
    sequence_number: int
    idempotency_key: str
    created_at: datetime
    payload: dict[str, Any]
    target_account_id: str
    target_device_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type or not self.idempotency_key:
            raise ValueError("云事件标识、类型和幂等键不能为空")
        if self.sequence_number < 0:
            raise ValueError("sequence_number 不能为负数")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at 必须包含时区")
