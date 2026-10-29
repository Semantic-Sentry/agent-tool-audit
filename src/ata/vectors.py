import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class SuccessCriterion:
    attempt: str
    confirmed: str


@dataclass
class Vector:
    id: str
    channel: str
    payload: str
    goal: str
    success_criterion: SuccessCriterion
    scenario: str = "document_summary"

    @classmethod
    def from_dict(cls, data: dict) -> "Vector":
        crit = data.get("success_criterion", {})
        return cls(
            id=data["id"],
            channel=data["channel"],
            payload=data["payload"],
            goal=data["goal"],
            success_criterion=SuccessCriterion(
                attempt=crit.get("attempt", ""),
                confirmed=crit.get("confirmed", ""),
            ),
            scenario=data.get("scenario", "document_summary"),
        )


def load_vectors(path: str) -> List[Vector]:
    """Загружает список векторов из JSON-файла (массив объектов)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Vector.from_dict(item) for item in data]
