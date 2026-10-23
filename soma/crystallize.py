"""TB-011: Crystallize status block — Status lines for a prepared list of build stages.

No set frames. Stops on FAIL. Close line varies on success vs fail.
"""
from __future__ import annotations

import io

from write_status import write_status


_ALLOWED_NAMES = frozenset([
    "BLUEPRINT", "MONOLITH", "SLICE", "HARDEN", "EXECUTE", "GATE", "PUBLISH",
])


def write_crystallize(stages: list[dict], stream: io.TextIOBase) -> str:
    """Append status lines for a prepared list of build stages.

    Parameters
    ----------
    stages : list[dict]
        Each dict has keys:
        - 'name' (str): one of the allowed names
        - 'outcome' (str | None): None = running, 'SUCCESS' | 'FAIL'
        - 'count_verified' (int, optional): verified count
        - 'count_failed' (int, optional): failed count
    stream : io.TextIOBase
        Output stream.

    Returns
    -------
    str
        The full output written to stream.
    """
    blocks: list[str] = []

    for stage in stages:
        name = stage["name"]
        outcome = stage.get("outcome")

        if outcome is None:
            # Running — CR line
            write_status(name, None, stream)
            # Don't add to blocks yet (will be overwritten)
            continue

        if outcome == "SUCCESS":
            verified = stage.get("count_verified", 0)
            failed = stage.get("count_failed", 0)
            line = f"-[{name}]- Running. . . . . . . -[SUCCESS]-   verified {verified}  failed {failed}"
            blocks.append(line + "\n")
            # Write directly (no overwrite)
            stream.write(line + "\n")
            continue

        # outcome == "FAIL" — stop the block
        line = f"-[{name}]- Running. . . . . . . -[FAIL]-"
        blocks.append(line + "\n")
        stream.write(line + "\n")
        # Close line on fail
        close = f"STATE  KILL  stage={name}. Nothing published after the failure."
        stream.write(close + "\n")
        blocks.append(close + "\n")
        return "".join(blocks)

    # All stages succeeded
    published = len(stages)
    stream.write(f"STATE  NEXT  published {published}. failed slot stays unwritten.\n")
    return "".join(blocks) + f"STATE  NEXT  published {published}. failed slot stays unwritten.\n"
