from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from src.core.components import Component
from src.core.engine import Engine
from src.core.events import Event

M = TypeVar("M")  # mode type

ConstraintCheck = Callable[[Engine, Event, Component], bool]


@dataclass(slots=True)
class Constraint:
    """
    A named boolean check using the same triple as component handlers:
    ``(engine, event, component)``.
    """

    name: str
    check: ConstraintCheck

    def matches(self, engine: Engine, event: Event, component: Component) -> bool:
        return self.check(engine, event, component)


@dataclass(slots=True)
class ModeRule(Generic[M]):
    """
    A rule that yields a mode if all its constraints pass.
    Higher priority rules are checked first.
    """

    name: str
    mode: M
    priority: int = 0
    enabled: bool = True
    constraints: list[Constraint] = field(default_factory=list)

    def matches(self, engine: Engine, event: Event, component: Component) -> bool:
        if not self.enabled:
            return False
        return all(
            constraint.matches(engine, event, component) for constraint in self.constraints
        )


class ModeResolver(Generic[M]):
    """
    Centralized rule store and mode evaluator.
    """

    def __init__(self) -> None:
        self._rules: list[ModeRule[M]] = []

    def add_rule(self, rule: ModeRule[M]) -> None:
        if any(existing.name == rule.name for existing in self._rules):
            raise ValueError(f"Rule with name {rule.name!r} already exists")
        self._rules.append(rule)
        self._sort_rules()

    def remove_rule(self, name: str) -> None:
        original_len = len(self._rules)
        self._rules = [rule for rule in self._rules if rule.name != name]
        if len(self._rules) == original_len:
            raise KeyError(f"No rule named {name!r}")

    def replace_rule(self, name: str, new_rule: ModeRule[M]) -> None:
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                if new_rule.name != name and any(r.name == new_rule.name for r in self._rules):
                    raise ValueError(f"Rule with name {new_rule.name!r} already exists")
                self._rules[i] = new_rule
                self._sort_rules()
                return
        raise KeyError(f"No rule named {name!r}")

    def enable_rule(self, name: str) -> None:
        self._get_rule(name).enabled = True

    def disable_rule(self, name: str) -> None:
        self._get_rule(name).enabled = False

    def get_rule(self, name: str) -> ModeRule[M]:
        return self._get_rule(name)

    def list_rules(self) -> list[ModeRule[M]]:
        return list(self._rules)

    def clear_rules(self) -> None:
        self._rules.clear()

    def resolve(
        self,
        engine: Engine,
        event: Event,
        component: Component,
        default: M | None = None,
    ) -> M | None:
        for rule in self._rules:
            if rule.matches(engine, event, component):
                return rule.mode

        return default

    def explain(
        self, engine: Engine, event: Event, component: Component
    ) -> list[tuple[str, bool]]:
        """
        Returns [(rule_name, matched), ...] in evaluation order.
        Useful for debugging.
        """
        return [
            (rule.name, rule.matches(engine, event, component)) for rule in self._rules
        ]

    def _get_rule(self, name: str) -> ModeRule[M]:
        for rule in self._rules:
            if rule.name == name:
                return rule
        raise KeyError(f"No rule named {name!r}")

    def _sort_rules(self) -> None:
        self._rules.sort(key=lambda rule: rule.priority, reverse=True)
