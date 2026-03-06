from typing import Iterable

from components import Component, SinkComponent


def get_records_as_printable_string(components: Iterable[Component]) -> str:
    result = ""
    for component in components:
        if isinstance(component, SinkComponent):
            records = component.records
            if records:
                result += f"{component.component_id}: {records}\n"
    return result