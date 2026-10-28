from dataclasses import dataclass


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
        )
