from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")  # dataclass type
M = TypeVar("M")  # mode type


@dataclass(slots=True)
class Constraint(Generic[T]):
    """
    A named boolean check over a dataclass instance.
    """
    name: str
    check: Callable[[T], bool]

    def matches(self, obj: T) -> bool:
        return self.check(obj)


@dataclass(slots=True)
class ModeRule(Generic[T, M]):
    """
    A rule that yields a mode if all its constraints pass.
    Higher priority rules are checked first.
    """
    name: str
    mode: M
    priority: int = 0
    enabled: bool = True
    constraints: list[Constraint[T]] = field(default_factory=list)

    def matches(self, obj: T) -> bool:
        if not self.enabled:
            return False
        return all(constraint.matches(obj) for constraint in self.constraints)


class ModeResolver(Generic[T, M]):
    """
    Centralized rule store and mode evaluator.
    """
    def __init__(self) -> None:
        self._rules: list[ModeRule[T, M]] = []

    def add_rule(self, rule: ModeRule[T, M]) -> None:
        if any(existing.name == rule.name for existing in self._rules):
            raise ValueError(f"Rule with name {rule.name!r} already exists")
        self._rules.append(rule)
        self._sort_rules()

    def remove_rule(self, name: str) -> None:
        original_len = len(self._rules)
        self._rules = [rule for rule in self._rules if rule.name != name]
        if len(self._rules) == original_len:
            raise KeyError(f"No rule named {name!r}")

    def replace_rule(self, name: str, new_rule: ModeRule[T, M]) -> None:
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

    def get_rule(self, name: str) -> ModeRule[T, M]:
        return self._get_rule(name)

    def list_rules(self) -> list[ModeRule[T, M]]:
        return list[ModeRule[T, M]](self._rules)

    def clear_rules(self) -> None:
        self._rules.clear()

    def resolve(self, obj: T, default: M | None = None) -> M | None:
        if not is_dataclass(obj):
            raise TypeError("resolve() expects a dataclass instance")

        for rule in self._rules:
            if rule.matches(obj):
                return rule.mode

        return default

    def explain(self, obj: T) -> list[tuple[str, bool]]:
        """
        Returns [(rule_name, matched), ...] in evaluation order.
        Useful for debugging.
        """
        if not is_dataclass(obj):
            raise TypeError("explain() expects a dataclass instance")

        return [(rule.name, rule.matches(obj)) for rule in self._rules]

    def _get_rule(self, name: str) -> ModeRule[T, M]:
        for rule in self._rules:
            if rule.name == name:
                return rule
        raise KeyError(f"No rule named {name!r}")

    def _sort_rules(self) -> None:
        self._rules.sort(key=lambda rule: rule.priority, reverse=True)


    