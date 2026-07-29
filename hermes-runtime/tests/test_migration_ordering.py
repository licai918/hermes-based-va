"""A backfilled migration number must not apply in two different orders.

THE BUG THIS FILE EXISTS FOR. ``run_migrations`` decides what to apply by SET
membership (``if version in already_applied: continue``) and iterates in LEXICAL
order. Those two facts are individually correct and jointly produce drift:

* a **fresh** database applies ``0027`` in its numeric position, before 0028–0031;
* a database that **already has** 0028–0031 applies ``0027`` last, after them.

Same migration directory, two different execution orders, decided by when the
database happened to be created. A backfilled ``0027`` that references a table
0028 creates works on the old database and fails on a fresh one — or the reverse,
which is worse because it is silent.

WHY THIS IS LIVE RATHER THAN THEORETICAL. 0.0.5's D1 allocated 0027 to S25, S25
landed without needing a migration, and D1 now records the prefix as **FREE** —
which reads as an invitation to backfill it. Nobody has yet. This closes the door
before someone does.

The runner already understands the shape of this hazard elsewhere: D1's own note
on 0031 explains that editing an applied migration "would constrain fresh
databases while silently skipping already-migrated ones". This is the mirror
image and had no guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_runtime.datastore.migrate import run_migrations


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        if sql.strip().startswith("SELECT version"):
            self._conn._select_pending = True
            return
        if "INSERT INTO schema_migrations" in sql:
            self._conn.applied.append(params[0])
            return
        if "CREATE TABLE IF NOT EXISTS schema_migrations" in sql:
            return
        self._conn.ran.append(sql.strip())

    def fetchall(self) -> list[tuple[str]]:
        assert self._conn._select_pending, "fetchall() without the version SELECT"
        self._conn._select_pending = False
        return [(v,) for v in self._conn.applied]


class _FakeConn:
    """Records what a migration run executes, in order. No database needed.

    Deliberately a recorder rather than a mock with expectations: the property
    under test IS the order, so the test reads it out rather than asserting a
    call sequence it also had to write down.
    """

    def __init__(self, already_applied: list[str] | None = None) -> None:
        self.applied: list[str] = list(already_applied or [])
        self.ran: list[str] = []
        self._select_pending = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        return None


def _write(tmp_path: Path, *versions: str) -> Path:
    for version in versions:
        (tmp_path / f"{version}.sql").write_text(
            f"-- {version}\nSELECT '{version}';\n", encoding="utf-8"
        )
    return tmp_path


def test_a_backfilled_number_is_refused_on_a_database_that_moved_past_it(tmp_path):
    """The one that reddens: silent out-of-order application.

    A database already carrying 0028 is handed a directory that has grown a
    0027. Applying it here runs it AFTER 0028, while a fresh database would run
    it BEFORE — so the runner must refuse rather than pick one silently.
    """
    migrations = _write(tmp_path, "0026_a", "0027_backfilled", "0028_b")
    conn = _FakeConn(already_applied=["0026_a", "0028_b"])

    with pytest.raises(RuntimeError) as excinfo:
        run_migrations(conn, migrations)

    message = str(excinfo.value)
    assert "0027_backfilled" in message, "the refusal must name the offending version"
    assert "0028_b" in message, "and what it would have been applied after"
    assert conn.ran == [], "nothing may be applied once the run is refused"


def test_a_fresh_database_applies_the_same_directory_in_numeric_order(tmp_path):
    """The other half: the guard must not break the normal case.

    The same directory, on a database that has applied nothing, is exactly the
    situation the refusal above is protecting — so it has to work.
    """
    migrations = _write(tmp_path, "0026_a", "0027_backfilled", "0028_b")

    conn = _FakeConn()
    applied = run_migrations(conn, migrations)

    assert applied == ["0026_a", "0027_backfilled", "0028_b"]


def test_appending_the_next_number_is_still_an_ordinary_run(tmp_path):
    """The overwhelmingly common case must stay boring.

    A new migration whose number is higher than everything applied is not
    out-of-order and must not be refused — otherwise the guard would block every
    normal deploy and get removed.
    """
    migrations = _write(tmp_path, "0026_a", "0027_b", "0028_new")
    conn = _FakeConn(already_applied=["0026_a", "0027_b"])

    applied = run_migrations(conn, migrations)

    assert applied == ["0028_new"]


def test_staging_a_migration_on_purpose_is_still_possible(tmp_path):
    """The escape hatch, pinned — because a guard with no legitimate exit gets deleted.

    Proving a nullable ALTER does not backfill requires applying it after rows
    exist, i.e. staged behind later migrations. That is a knowing act, so it is
    spelled rather than defaulted.
    """
    migrations = _write(tmp_path, "0026_a", "0027_staged", "0028_b")
    conn = _FakeConn(already_applied=["0026_a", "0028_b"])

    applied = run_migrations(conn, migrations, allow_out_of_order=True)

    assert applied == ["0027_staged"]


def test_an_excluded_migration_does_not_count_as_a_gap(tmp_path):
    """`exclude` is how the dev seed is skipped; skipping is not backfilling.

    Without this the guard would fire on every test schema that excludes
    0005_dev_bootstrap, which is the runner's own documented workflow.
    """
    migrations = _write(tmp_path, "0026_a", "0027_seed", "0028_b")
    conn = _FakeConn(already_applied=["0026_a", "0028_b"])

    applied = run_migrations(conn, migrations, exclude=("0027_seed",))

    assert applied == []
