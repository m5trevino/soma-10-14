from store import Soma
from typing import Any, Optional


def get_receptor_config(soma: Soma, name: str) -> Optional[dict[str, Any]]:
    """Query ReceptorConfig nodes and return the one matching *name*."""
    for node in soma.query_by_type("ReceptorConfig"):
        if node.properties.get("name") == name or node.properties.get("stage") == name:
            return node.properties
    return None


def put_receptor_config(soma: Soma, name: str, instruction_body: str, stage: str | None = None) -> str:
    """Create or update a ReceptorConfig node."""
    props = {
        "name": name,
        "instruction_body": instruction_body,
        "stage": stage or name,
    }
    nid = f"config-{name}"
    existing = soma.get_node(nid)
    if existing:
        existing.properties.update(props)
    else:
        soma.create_node("ReceptorConfig", props)
    return nid