from processor import process_file

ALLOWED_STATUSES = {
    "valid",
    "expiring",
    "expired",
    "missing",
    "flagged",
    "new",
    "duplicate",
    "login_required",
    "sync_error",
    "portal_change_required",
}


def test_csv_processing() -> None:
    data = b"supplier,product,price\nAcme,Widget,9.99"
    records = process_file(data)

    assert isinstance(records, list)
    assert len(records) == 1

    record = records[0]
    assert set(record.keys()) == {"title", "status", "details", "due_date"}
    assert record["title"] == "Acme"
    assert record["status"] in ALLOWED_STATUSES
    assert isinstance(record["details"], dict)
    assert record["details"].get("price") == "9.99"
    assert "due_date" in record

    print("test_csv_processing passed")


def test_empty_input_returns_empty_list() -> None:
    assert process_file(b"") == []
    print("test_empty_input_returns_empty_list passed")


if __name__ == "__main__":
    test_csv_processing()
    test_empty_input_returns_empty_list()
    print("All tests passed")
