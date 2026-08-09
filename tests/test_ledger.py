from services.ledger import ReadAloudLedger


def test_mark_and_marked(tmp_path):
    ledger = ReadAloudLedger(tmp_path / "ledger.db")
    assert ledger.marked() == set()
    ledger.mark(["A", "B"])
    assert ledger.marked() == {"A", "B"}


def test_mark_is_idempotent(tmp_path):
    ledger = ReadAloudLedger(tmp_path / "ledger.db")
    ledger.mark(["A"])
    ledger.mark(["A"])
    assert ledger.marked() == {"A"}


def test_prune_drops_entries_not_still_unread(tmp_path):
    ledger = ReadAloudLedger(tmp_path / "ledger.db")
    ledger.mark(["A", "B", "C"])
    ledger.prune(still_unread={"B"})
    assert ledger.marked() == {"B"}


def test_persists_across_instances(tmp_path):
    ReadAloudLedger(tmp_path / "ledger.db").mark(["A"])
    assert ReadAloudLedger(tmp_path / "ledger.db").marked() == {"A"}
