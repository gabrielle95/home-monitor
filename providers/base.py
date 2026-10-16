from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Outage:
    provider: str
    utility: str
    external_id: str
    address_label: str
    start: datetime
    end: datetime
    description: str
    url: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.external_id}"

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d


class Provider(ABC):
    name: str
    utility: str

    @abstractmethod
    def fetch(self, address_cfg: dict[str, Any]) -> list[Outage]:
        ...
