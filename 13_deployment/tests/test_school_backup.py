from datetime import date, datetime
from decimal import Decimal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from school_backup import encode_value, snapshot


@pytest.mark.parametrize("value", [None, "stored-json", 17, 2.5, True])
def test_plain_values_retained(value):
    assert encode_value(value) == value


def test_typed_database_values_encoded_without_decryption():
    assert encode_value(b"encrypted-bytes") == {"type": "bytes", "value": "ZW5jcnlwdGVkLWJ5dGVz"}
    assert encode_value(datetime(2026, 10, 11)) == {"type": "datetime", "value": "2026-10-11T00:00:00"}
    assert encode_value(date(2026, 10, 11)) == {"type": "date", "value": "2026-10-11"}
    assert encode_value(Decimal("12.30")) == {"type": "decimal", "value": "12.30"}
    with pytest.raises(TypeError, match="Unsupported backup value"):
        encode_value(object())


class WrongTargetConnection:
    def __init__(self):
        self.rolled_back = False
        self.sql = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self.sql.append(sql)

    def fetchone(self):
        return ("unowned_database", 3306, "REPEATABLE-READ")

    def rollback(self):
        self.rolled_back = True


def test_wrong_database_rejected_before_content_read():
    connection = WrongTargetConnection()
    with pytest.raises(ValueError, match="Owned consistent snapshot target required"):
        snapshot(connection, {"database": "smhai_school_demo", "port": 3308})
    assert connection.rolled_back
    assert len(connection.sql) == 1
