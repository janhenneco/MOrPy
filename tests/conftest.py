import logging

import pytest


@pytest.fixture
def morpy_caplog(caplog, monkeypatch):
    logger = logging.getLogger("morpy")
    monkeypatch.setattr(logger, "propagate", True)
    caplog.set_level(logging.INFO, logger="morpy")
    return caplog
