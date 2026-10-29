"""A drill as data: scenario, prediction question, injected failure, evidence, verdict, explanation."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from demo_format import heading


class DrillFailure(Exception):
    """An expected way for a drill to fail (a service misbehaved); reported as a failed check."""


@dataclass(frozen=True)
class Check:
    description: str
    passed: bool


@dataclass(frozen=True)
class Outcome:
    checks: tuple[Check, ...]


@dataclass(frozen=True)
class Explanation:
    invariant: str
    mechanism: str
    without: str
    trade_off: str


@dataclass(frozen=True)
class Drill:
    number: int
    key: str
    title: str
    scenario: str
    question: str
    explanation: Explanation
    # Receives the drill context, prints evidence through its `say`, and returns the checks.
    act: Callable[[Any], Outcome]


def make_pause(interactive: bool, input_fn: Callable[[str], object] = input) -> Callable[[], None]:
    if not interactive:
        return lambda: None
    return lambda: input_fn("         think about it, then press Enter to inject the failure > ")


def select_drills(catalog: Sequence[Drill], selector: str) -> list[Drill]:
    if selector == "all":
        return list(catalog)
    by_number = {drill.number: drill for drill in catalog}
    if selector.isdigit() and int(selector) in by_number:
        return [by_number[int(selector)]]
    raise ValueError(f"choose a drill number 1-{len(catalog)} or 'all', not {selector!r}")


def run_drill(drill: Drill, context: Any, *, pause: Callable[[], None], out: Callable[[str], None]) -> bool:
    out(heading(f"Drill {drill.number}: {drill.title}"))
    out(f"SCENARIO {drill.scenario}")
    out(f"PREDICT  {drill.question}")
    pause()
    out("EVIDENCE")
    try:
        checks = drill.act(context).checks
    except DrillFailure as failure:
        checks = (Check(str(failure), False),)
    out("VERDICT")
    for check in checks:
        out(f"  [{'ok' if check.passed else 'FAIL'}] {check.description}")
    explanation = drill.explanation
    out("REVEAL")
    out(f"  invariant:  {explanation.invariant}")
    out(f"  mechanism:  {explanation.mechanism}")
    out(f"  without it: {explanation.without}")
    out(f"  trade-off:  {explanation.trade_off}")
    # A drill that asserts nothing proves nothing.
    return bool(checks) and all(check.passed for check in checks)
