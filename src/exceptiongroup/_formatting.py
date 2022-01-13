# traceback_exception_init() adapted from trio
#
# _ExceptionPrintContext and traceback_exception_format() copied from the standard
# library
from __future__ import annotations

import sys
import textwrap
import traceback
from collections.abc import Iterator
from types import TracebackType

from ._exceptions import BaseExceptionGroup

max_group_width = 15
max_group_depth = 10
_cause_message = (
    "\nThe above exception was the direct cause " "of the following exception:\n\n"
)

_context_message = (
    "\nDuring handling of the above exception, " "another exception occurred:\n\n"
)


def traceback_exception_init(
    self,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType,
    *,
    limit: int | None = None,
    lookup_lines: bool = True,
    capture_locals: bool = False,
    compact: bool = False,
    _seen: set[int] | None = None,
) -> None:
    if sys.version_info >= (3, 10):
        kwargs = {"compact": compact}
    else:
        kwargs = {}

    # Capture the original exception and its cause and context as TracebackExceptions
    traceback_exception_original_init(
        self,
        exc_type,
        exc_value,
        exc_traceback,
        limit=limit,
        lookup_lines=lookup_lines,
        capture_locals=capture_locals,
        _seen=_seen,
        **kwargs,
    )

    seen_was_none = _seen is None

    if _seen is None:
        _seen = set()

    # Capture each of the exceptions in the ExceptionGroup along with each of
    # their causes and contexts
    if isinstance(exc_value, BaseExceptionGroup):
        embedded = []
        for exc in exc_value.exceptions:
            if id(exc) not in _seen:
                embedded.append(
                    traceback.TracebackException.from_exception(
                        exc,
                        limit=limit,
                        lookup_lines=lookup_lines,
                        capture_locals=capture_locals,
                        # copy the set of _seen exceptions so that duplicates
                        # shared between sub-exceptions are not omitted
                        _seen=None if seen_was_none else set(_seen),
                    )
                )
        self.exceptions = embedded
        self.msg = exc_value.message
    else:
        self.exceptions = None


class _ExceptionPrintContext:
    def __init__(self):
        self.seen = set()
        self.exception_group_depth = 0
        self.need_close = False

    def indent(self):
        return " " * (2 * self.exception_group_depth)

    def emit(self, text_gen, margin_char=None):
        if margin_char is None:
            margin_char = "|"
        indent_str = self.indent()
        if self.exception_group_depth:
            indent_str += margin_char + " "

        if isinstance(text_gen, str):
            yield textwrap.indent(text_gen, indent_str, lambda line: True)
        else:
            for text in text_gen:
                yield textwrap.indent(text, indent_str, lambda line: True)


def traceback_exception_format(
    self: traceback.TracebackException,
    *,
    chain: bool = True,
    _ctx: _ExceptionPrintContext | None = None,
) -> Iterator[str]:
    if _ctx is None:
        _ctx = _ExceptionPrintContext()

    output = []
    exc = self
    if chain:
        while exc:
            if exc.__cause__ is not None:
                chained_msg = _cause_message
                chained_exc = exc.__cause__
            elif exc.__context__ is not None and not exc.__suppress_context__:
                chained_msg = _context_message
                chained_exc = exc.__context__
            else:
                chained_msg = None
                chained_exc = None

            output.append((chained_msg, exc))
            exc = chained_exc
    else:
        output.append((None, exc))

    for msg, exc in reversed(output):
        if msg is not None:
            yield from _ctx.emit(msg)
        if exc.exceptions is None:
            if exc.stack:
                yield from _ctx.emit("Traceback (most recent call last):\n")
                yield from _ctx.emit(exc.stack.format())
            yield from _ctx.emit(exc.format_exception_only())
        elif _ctx.exception_group_depth > max_group_depth:
            # exception group, but depth exceeds limit
            yield from _ctx.emit(f"... (max_group_depth is {max_group_depth})\n")
        else:
            # format exception group
            is_toplevel = _ctx.exception_group_depth == 0
            if is_toplevel:
                _ctx.exception_group_depth += 1

            if exc.stack:
                yield from _ctx.emit(
                    "Exception Group Traceback (most recent call last):\n",
                    margin_char="+" if is_toplevel else None,
                )
                yield from _ctx.emit(exc.stack.format())

            yield from _ctx.emit(exc.format_exception_only())
            num_excs = len(exc.exceptions)
            if num_excs <= max_group_width:
                n = num_excs
            else:
                n = max_group_width + 1
            _ctx.need_close = False
            for i in range(n):
                last_exc = i == n - 1
                if last_exc:
                    # The closing frame may be added by a recursive call
                    _ctx.need_close = True

                if max_group_width is not None:
                    truncated = i >= max_group_width
                else:
                    truncated = False
                title = f"{i+1}" if not truncated else "..."
                yield (
                    _ctx.indent()
                    + ("+-" if i == 0 else "  ")
                    + f"+---------------- {title} ----------------\n"
                )
                _ctx.exception_group_depth += 1
                if not truncated:
                    yield from exc.exceptions[i].format(chain=chain, _ctx=_ctx)
                else:
                    remaining = num_excs - max_group_width
                    plural = "s" if remaining > 1 else ""
                    yield from _ctx.emit(f"and {remaining} more exception{plural}\n")

                if last_exc and _ctx.need_close:
                    yield (_ctx.indent() + "+------------------------------------\n")
                    _ctx.need_close = False
                _ctx.exception_group_depth -= 1

            if is_toplevel:
                assert _ctx.exception_group_depth == 1
                _ctx.exception_group_depth = 0


def exceptiongroup_excepthook(
    etype: type[BaseException], value: BaseException, tb: TracebackType
) -> None:
    sys.stderr.write("".join(traceback.format_exception(etype, value, tb)))


traceback_exception_original_init = traceback.TracebackException.__init__
traceback.TracebackException.__init__ = traceback_exception_init
traceback_exception_original_format = traceback.TracebackException.format
traceback.TracebackException.format = traceback_exception_format

if sys.excepthook is sys.__excepthook__:
    sys.excepthook = exceptiongroup_excepthook
