"""History staging must be movable without depending on garbage collection."""
import sqlite3

import pytest

from gondola.kb import KB
from gondola.ledger import Ledger
from gondola.review.digests import Digests


@pytest.mark.parametrize("factory", [Ledger, KB, Digests])
def test_transaction_closes_connection_and_allows_history_move(tmp_path, factory):
    path = tmp_path / "stage.sqlite"
    store = factory(path)
    with store._con() as connection:
        connection.execute("CREATE TABLE lifecycle_probe (value INTEGER)")
    with pytest.raises(RuntimeError):
        with store._con() as connection:
            connection.execute("INSERT INTO lifecycle_probe VALUES (1)")
            raise RuntimeError("rollback")
    with store._con() as connection:
        cursor = connection.execute("SELECT COUNT(*) FROM lifecycle_probe")
        assert cursor.fetchone()[0] == 0
    # Keep both references alive: closing must be explicit, not eventual GC.
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    path.rename(tmp_path / "published.sqlite")
    assert (tmp_path / "published.sqlite").exists()
