from typing import Iterable


def get_records_as_printable_string(components: Iterable) -> str:
    """Format records from any component that has a 'records' attribute (e.g. SinkComponent)."""
    result = ""
    for component in components:
        records = getattr(component, "records", None)
        if records is not None:
            component_id = getattr(component, "component_id", id(component))
            result += f"{component_id}: {list(records)}\n"
    return result if result else "(no sink records)\n"