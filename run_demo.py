from processor import process_file


def main() -> int:
    test_bytes = b"supplier,product,price\nAcme,Widget,9.99"
    results = process_file(test_bytes)
    assert isinstance(results, list)
    assert len(results) == 1

    print("PortalSync demo: processed sample CSV")
    for record in results:
        print(record)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
