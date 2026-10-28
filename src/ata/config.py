import copy
import hashlib
import json
from dataclasses import dataclass, asdict, field
from typing import List
from ata.policy import PolicyConfig, ToolClass
from ata.vectors import Vector


def _canonical_json(obj) -> str:
    """Детерминированная сериализация: сортированные ключи, без пробелов-сюрпризов."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class AuditConfig:
    """
    Всё, что определяет 'что именно тестировалось' и что должно быть
    зафиксировано ДО прогона (внешний якорь №1).
    """
    agent_name: str
    model: str              # например "openai/gpt-4o-2024-11-20" — точный snapshot, не алиас
    model_provider: str      # например "openrouter"
    n_iterations: int
    policy: PolicyConfig
    vector_ids: List[str]    # id векторов, включённых в прогон (не весь payload — он в vectors/*.json)
    framework: str = "none"  # "langchain" | "crewai" | "none" (для fake-agent тестов)
    framework_version: str = "unknown"
    ata_version: str = "0.1.0"
    extra: dict = field(default_factory=dict)  # для любых доп. параметров без смены схемы

    def __post_init__(self):
        # Замораживаем снимок policy в момент создания конфига — защита
        # от случайной мутации того же объекта policy после того, как
        # его хэш уже мог быть отправлен клиенту как внешний якорь.
        self.policy = copy.deepcopy(self.policy)

    def to_canonical_dict(self) -> dict:
        policy_dict = {
            "agent_name": self.policy.agent_name,
            "untrusted_channels": sorted(self.policy.untrusted_channels),
            "tools": {
                name: {
                    "class": tp.class_type.value,
                    "allowed_domains": sorted(tp.allowed_domains),
                    "allowed_recipients": sorted(tp.allowed_recipients),
                }
                for name, tp in self.policy.tools.items()
            },
        }
        return {
            "agent_name": self.agent_name,
            "model": self.model,
            "model_provider": self.model_provider,
            "n_iterations": self.n_iterations,
            "policy": policy_dict,
            "vector_ids": sorted(self.vector_ids),
            "framework": self.framework,
            "framework_version": self.framework_version,
            "ata_version": self.ata_version,
            "extra": self.extra,
        }

    def config_hash(self) -> str:
        return _sha256(_canonical_json(self.to_canonical_dict()))

    def to_json_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_canonical_dict(), f, sort_keys=True, ensure_ascii=False, indent=2)
