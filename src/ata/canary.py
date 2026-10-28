import uuid


def generate_canary(run_id: str, vector_id: str, iteration: int) -> str:
    """
    Уникальная канарейка на каждую пару (вектор, итерация) в рамках прогона.
    Уникальность важна: захват в sink должен однозначно связываться
    с конкретной итерацией, а не просто с фактом инъекции вообще.
    """
    unique = uuid.uuid4().hex[:8]
    return f"CANARY-{run_id}-{vector_id}-{iteration}-{unique}"


def seed_payload(template: str, canary: str) -> str:
    """Подставляет канарейку в шаблон вектора (плейсхолдер {CANARY})."""
    return template.replace("{CANARY}", canary)
