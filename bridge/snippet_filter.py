"""``rg --json`` snippet filter extracted from the Bridge.

Used exclusively by ``find_symbol`` to scope symbol results by source-code
snippet occurrences.  Takes a list of symbols, a snippet string, and a
project root, and returns the subset of symbols whose source location
overlaps with an ``rg`` match.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict

from solidlsp.ls_types import UnifiedSymbolInformation

_RG_JSON_LINE_RE = re.compile(r"^\s*\{")


def filter_by_snippet(
    symbols: list[UnifiedSymbolInformation],
    snippet: str,
    cwd: str,
    within_path: str | None,
) -> list[UnifiedSymbolInformation]:
    """Run ``rg --json`` for *snippet* and keep only symbols whose
    location falls within a snippet occurrence.

    ``rg`` must be available on ``PATH``.
    """
    cmd = ["rg", "--json", "-F"]
    if "\n" in snippet:
        cmd.append("--multiline")
    cmd.extend(["-e", snippet])
    if within_path is not None:
        cmd.append(within_path)
    else:
        cmd.append(".")

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"rg command failed: {exc}") from exc

    occurrences: list[tuple[str, int, int]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if not _RG_JSON_LINE_RE.match(line):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data")
        if not isinstance(data, dict):
            continue
        path_info = data.get("path")
        if not isinstance(path_info, dict):
            continue
        file_path = path_info.get("text")
        if not isinstance(file_path, str):
            continue
        line_num = data.get("line_number")
        if not isinstance(line_num, int):
            continue
        lines_data = data.get("lines")
        if isinstance(lines_data, dict):
            text = lines_data.get("text", "")
            num_lines = text.count("\n") + 1 if text else 1
        else:
            num_lines = 1
        start_line = line_num - 1
        end_line = start_line + num_lines - 1
        occurrences.append((file_path, start_line, end_line))

    if not occurrences:
        return []

    occ_map: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for fp, sl, el in occurrences:
        normalized = fp.lstrip("./") or "."
        occ_map[normalized].append((sl, el))

    result: list[UnifiedSymbolInformation] = []
    for sym in symbols:
        loc = sym.get("location")
        if loc is None:
            continue
        rel = loc.get("relativePath")
        if rel is None:
            continue
        rng = loc.get("range")
        if rng is None:
            continue
        sym_start = rng["start"]["line"]
        sym_end = rng["end"]["line"]

        rel_norm = str(rel).lstrip("./") or "."
        for occ_start, occ_end in occ_map.get(rel_norm, []):
            if sym_start <= occ_end and sym_end >= occ_start:
                result.append(sym)
                break

    return result
