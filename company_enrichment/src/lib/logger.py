"""
Plain stdout logging - monday-code ships stdout to `mapps code:logs -t console`.
Message shapes are kept identical to the previous deployment so historic log
searches (`Action received`, `Background enrichment done`) keep matching.

Flushed on every line: a container's stdout is block-buffered, and a run that
dies mid-way would otherwise take its last log lines with it.
"""
import sys


def log(*parts):
    print(*parts, flush=True)


def log_error(*parts):
    print(*parts, file=sys.stderr, flush=True)
