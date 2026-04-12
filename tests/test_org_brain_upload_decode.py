from __future__ import annotations

import pytest
from fastapi import HTTPException

from gateway.http.routes.org_brain import _decode_upload_to_text


def test_decode_plain_text_upload():
    text = _decode_upload_to_text("policy.txt", b"Line A\nLine B")
    assert "Line A" in text
    assert "Line B" in text


def test_decode_csv_upload():
    text = _decode_upload_to_text("table.csv", b"col1,col2\na,b\n")
    assert "col1,col2" in text
    assert "a,b" in text


def test_decode_json_upload():
    text = _decode_upload_to_text("meta.json", b'{"k":"v","n":1}')
    assert '"k": "v"' in text


def test_decode_unsupported_upload_type():
    with pytest.raises(HTTPException):
        _decode_upload_to_text("archive.bin", b"\x00\x01\x02")
