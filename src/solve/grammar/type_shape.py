"""Coarse textual type-shape parsers for typed grammar generation.

These helpers intentionally do not prove anything. They only find unambiguous
outer binary connectives in pretty-printed Lean types so replay can avoid the
largest class of nonsense candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {close: open_ for open_, close in _OPEN_TO_CLOSE.items()}
_SIMPLE_TERM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_'.]*$")


@dataclass(frozen=True)
class ParsedBinary:
    """A parsed outer binary proposition with an optional leading forall."""

    lhs: str
    rhs: str
    binders: str = ""

    def __iter__(self):
        yield self.lhs
        yield self.rhs

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> str:
        return (self.lhs, self.rhs)[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ParsedBinary):
            return (self.lhs, self.rhs, self.binders) == (other.lhs, other.rhs, other.binders)
        if isinstance(other, tuple):
            if len(other) == 2:
                return (self.lhs, self.rhs) == other
            if len(other) == 3:
                return (self.binders, self.lhs, self.rhs) == other
        return False


def _compact(text: str) -> str:
    return " ".join(text.strip().split())


def _scan_top_level(text: str, token: str) -> tuple[list[int], bool]:
    positions: list[int] = []
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in _OPEN_TO_CLOSE:
            stack.append(char)
            index += 1
            continue
        if char in _CLOSE_TO_OPEN:
            if not stack or stack[-1] != _CLOSE_TO_OPEN[char]:
                return [], False
            stack.pop()
            index += 1
            continue
        if not stack and text.startswith(token, index):
            positions.append(index)
            index += len(token)
            continue
        index += 1
    return positions, not stack


def _is_balanced(text: str) -> bool:
    _, balanced = _scan_top_level(text, "\0")
    return balanced


def _strip_leading_forall(text: str) -> tuple[str, str] | None:
    stripped = _compact(text)
    if not stripped.startswith("∀"):
        return "", stripped

    commas, balanced = _scan_top_level(stripped, ",")
    if not balanced or not commas:
        return None

    comma = commas[0]
    binders = stripped[: comma + 1].strip()
    body = stripped[comma + 1 :].strip()
    if not body:
        return None
    return binders, body


def _parse_binary(type_pp: str, tokens: tuple[str, ...]) -> ParsedBinary | None:
    try:
        stripped = _strip_leading_forall(type_pp)
    except Exception:
        return None
    if stripped is None:
        return None
    binders, body = stripped
    if not _is_balanced(body):
        return None

    candidates: list[tuple[int, str]] = []
    for token in tokens:
        positions, balanced = _scan_top_level(body, token)
        if not balanced:
            return None
        candidates.extend((position, token) for position in positions)
    if len(candidates) != 1:
        return None

    position, token = candidates[0]
    lhs = body[:position].strip()
    rhs = body[position + len(token) :].strip()
    if not lhs or not rhs:
        return None
    if not _is_balanced(lhs) or not _is_balanced(rhs):
        return None
    return ParsedBinary(lhs=lhs, rhs=rhs, binders=binders)


def parse_equality(type_pp: str) -> ParsedBinary | None:
    """Parse an unambiguous outer ``=`` proposition."""
    return _parse_binary(type_pp, ("=",))


def parse_iff(type_pp: str) -> ParsedBinary | None:
    """Parse an unambiguous outer ``↔`` proposition."""
    return _parse_binary(type_pp, ("↔",))


def parse_implication(type_pp: str) -> ParsedBinary | None:
    """Parse an unambiguous outer ``→`` proposition."""
    return _parse_binary(type_pp, ("→", "->"))


def render_statement(parsed: ParsedBinary, lhs: str, connective: str, rhs: str) -> str:
    core = f"{lhs.strip()} {connective} {rhs.strip()}"
    if parsed.binders:
        return f"{parsed.binders} {core}"
    return core


def lean_argument(term: str) -> str:
    stripped = term.strip()
    if _SIMPLE_TERM_RE.match(stripped):
        return stripped
    if len(stripped) >= 2 and stripped[0] in _OPEN_TO_CLOSE and _OPEN_TO_CLOSE[stripped[0]] == stripped[-1]:
        return stripped
    return f"({stripped})"
