# SPDX-License-Identifier: MIT
# tests/test_session_log_currency.py
"""docs/session-log.md's own header frames it as this project's working
narrative, but nothing enforced that narrative staying current: three
separate incidents (the #394-era gap, #513 opened 2026-09-18, #516 filed
2026-09-20) each found substantive PRs landing for three-to-five-day
stretches with no corresponding entry, caught only by luck of a later
scheduled audit noticing -- never by a mechanical gate.

This closes that loop with the simplest check that needs no git history at
all. A git-log-based "when did the last substantive commit land" check
would be unreliable here: this repo's CI checks out with `fetch-depth: 2`
(too shallow to walk back further), and on a `pull_request` run the
checked-out HEAD is GitHub's synthetic merge-ref commit, not the PR's own
commit -- its message and parentage aren't a reliable signal of what the
PR actually touched. Comparing the log's newest header to *today's* date
sidesteps both problems entirely: for a push-triggered run "today" IS
(within hours of) the landing commit's own date, and it's close enough for
a PR run authored around the same time.

This is NOT a perfect per-commit "did *this* commit need an entry" check --
it says nothing about whether an entry that does exist is any good. It's a
maintained tripwire against the multi-day silent drift the three incidents
above actually found, mirroring this repo's existing "good enough,
mechanically checked" gates (see
tests/test_ci_python_filter_covers_known_reads.py's own docstring for the
same trade-off made explicitly elsewhere).

A dependency-only PR landing after a quiet stretch used to trip this
through no fault of its own (#548) -- e.g. a Dependabot bump that touches
only requirements.txt, days after the log last got an entry from someone
else's unrelated PR. ci.yml's `tests` step now exports CI_EVENT_NAME plus
the pre-existing `python`/`session_log` paths-filter outputs as
CI_FILTER_PYTHON/CI_FILTER_SESSION_LOG; `_should_enforce_pr_diff_gate`
below uses them to skip the assertion on a `pull_request` run whose own
diff can't plausibly be the cause -- it doesn't touch anything in the
`python` filter group, or it already updates docs/session-log.md itself.
`push`/`schedule` runs (and a contributor's local `pytest`, which sets
none of these vars) keep the original unconditional calendar check: there
is no single PR diff to reason about there, and that is exactly the "many
small, individually-innocent merges left the log stale" case this test
exists to catch.

Bump _SLACK_DAYS if this fires on a legitimate quiet stretch; do not delete
or skip the test to silence it.
"""

import os
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = ROOT / "docs" / "session-log.md"

_HEADER_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})", re.MULTILINE)

# Generous on purpose: real work on this repo happens most days, but a
# legitimate quiet stretch (holidays, owner-only weeks) shouldn't be a false
# alarm. The three incidents this test guards against each ran 3-5 days
# before being caught -- this is set to fire before that repeats, not to
# fire on every multi-day gap.
_SLACK_DAYS = 5


def _latest_header_date(text: str) -> date:
    dates = _HEADER_DATE_RE.findall(text)
    assert dates, (
        f"{SESSION_LOG} has no '## YYYY-MM-DD' headers at all -- has its "
        "format changed? Update this test's parsing either way."
    )
    return max(date.fromisoformat(d) for d in dates)


def _is_stale(last_log_date: date, today: date, slack_days: int = _SLACK_DAYS) -> bool:
    return (today - last_log_date).days > slack_days


def _should_enforce_pr_diff_gate(env: dict[str, str] | None = None) -> bool:
    """Decide whether the calendar-staleness assertion applies to this run.

    `push`/`schedule` runs, and any invocation that doesn't set
    CI_EVENT_NAME at all (a contributor's local `pytest`), always enforce
    -- unconditional, same as before #548. A `pull_request` run only
    enforces when its own diff touches something in the `python`
    paths-filter group (CI_FILTER_PYTHON == "true") without also adding a
    docs/session-log.md entry in the same diff (CI_FILTER_SESSION_LOG !=
    "true"); otherwise this PR's own change can't be the cause of the
    drift and the assertion is skipped.
    """
    env = os.environ if env is None else env
    if env.get("CI_EVENT_NAME") != "pull_request":
        return True
    touches_python = env.get("CI_FILTER_PYTHON") == "true"
    touches_session_log = env.get("CI_FILTER_SESSION_LOG") == "true"
    return touches_python and not touches_session_log


@pytest.mark.parametrize(
    ("last_log_date", "expected", "reason"),
    [
        (date(2026, 9, 15), False, "exactly at the slack boundary should not be stale"),
        (date(2026, 9, 14), True, "one day past the slack boundary should be stale"),
        (date(2026, 9, 20), False, "zero gap should never be stale"),
        (
            date(2026, 9, 25),
            False,
            "a future date alone isn't rejected here -- test_session_log_is_current's separate last <= today assertion does that",
        ),
    ],
)
def test_is_stale_pure_logic(last_log_date, expected, reason):
    base = date(2026, 9, 20)
    assert _is_stale(last_log_date, base, slack_days=5) is expected, reason


def test_latest_header_date_picks_the_max_not_the_last_occurrence():
    # Headers are expected in chronological order, but the parser doesn't
    # rely on that -- a manually-inserted backfill entry (exactly what
    # landed earlier in this file, out of file-order, still in date order)
    # must not fool it into picking an earlier date just because it's the
    # last line in a snippet.
    text = "## 2026-09-10 — a\n\n## 2026-09-05 — b\n"
    assert _latest_header_date(text) == date(2026, 9, 10)


@pytest.mark.parametrize(
    ("env", "expected", "reason"),
    [
        ({}, True, "no CI_EVENT_NAME (local pytest) always enforces"),
        (
            {"CI_EVENT_NAME": "push"},
            True,
            "push always enforces regardless of filter outputs",
        ),
        (
            {"CI_EVENT_NAME": "schedule"},
            True,
            "schedule always enforces -- no single diff to reason about",
        ),
        (
            {"CI_EVENT_NAME": "pull_request", "CI_FILTER_PYTHON": "false"},
            False,
            "PR touching nothing in the python filter group can't be the cause",
        ),
        (
            {
                "CI_EVENT_NAME": "pull_request",
                "CI_FILTER_PYTHON": "true",
                "CI_FILTER_SESSION_LOG": "true",
            },
            False,
            "PR already updates docs/session-log.md itself in the same diff",
        ),
        (
            {
                "CI_EVENT_NAME": "pull_request",
                "CI_FILTER_PYTHON": "true",
                "CI_FILTER_SESSION_LOG": "false",
            },
            True,
            "PR touches substantive code without a session-log entry -- still flagged",
        ),
    ],
)
def test_should_enforce_pr_diff_gate(env, expected, reason):
    assert _should_enforce_pr_diff_gate(env) is expected, reason


def test_session_log_is_current():
    if not _should_enforce_pr_diff_gate():
        pytest.skip(
            "pull_request run whose own diff doesn't touch a path that "
            "needs a session-log entry, or that already adds one itself "
            "-- calendar staleness is still enforced on push/schedule (#548)."
        )
    text = SESSION_LOG.read_text(encoding="utf-8")
    last = _latest_header_date(text)
    # UTC, matching this repo's other date-stamped automation (the weekly
    # `schedule: cron` trigger in ci.yml is itself UTC) -- a naive
    # date.today() would silently use the runner's local timezone instead.
    today = datetime.now(UTC).date()
    # A future-dated header (a typo, or a clock skew during authoring) would
    # otherwise make `_is_stale` report "not stale" for the wrong reason --
    # catch that case explicitly rather than let it pass silently.
    assert last <= today, (
        f"docs/session-log.md's newest entry is dated {last}, which is in "
        f"the future relative to today ({today}) -- check for a typo."
    )
    assert not _is_stale(last, today), (
        f"docs/session-log.md's newest entry is dated {last}, more than "
        f"{_SLACK_DAYS} days before today ({today}). This has silently "
        "drifted before (the #394-era gap, #513, #516) -- add a "
        "session-log entry for whatever substantive work has landed "
        "since, even a short one, before merging."
    )
