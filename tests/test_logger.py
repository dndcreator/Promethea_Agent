import logging

from utils.logger import RepeatedAccessFilter


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_repeated_access_filter_bounds_only_identical_requests():
    request_filter = RepeatedAccessFilter(interval_s=60)

    assert request_filter.filter(_access_record("/health")) is True
    assert request_filter.filter(_access_record("/health")) is False
    assert request_filter.filter(_access_record("/workbench/snapshot")) is True
