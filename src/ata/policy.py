from enum import Enum
from typing import Dict, List
from dataclasses import dataclass, field


class ToolClass(str, Enum):
    SAFE = "safe"
    EGRESS = "egress"
    FORBIDDEN = "forbidden"


@dataclass
class ToolPolicy:
    class_type: ToolClass
    allowed_domains: List[str] = field(default_factory=list)
    allowed_recipients: List[str] = field(default_factory=list)


@dataclass
class PolicyConfig:
    agent_name: str
    untrusted_channels: List[str]
    tools: Dict[str, ToolPolicy]

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyConfig":
        tools = {}
        for name, cfg in data.get("tools", {}).items():
            tools[name] = ToolPolicy(
                class_type=ToolClass(cfg.get("class", "safe")),
                allowed_domains=cfg.get("allowed_domains", []),
                allowed_recipients=cfg.get("allowed_recipients", []),
            )
        return cls(
            agent_name=data.get("agent", "unknown"),
            untrusted_channels=data.get("untrusted_channels", []),
            tools=tools,
        )
