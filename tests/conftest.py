import os

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
FIXTURE = os.path.join(ROOT, "fixtures", "speed-demon.sample.html")
TEMPLATES = os.path.join(ROOT, "templates", "digits.json")


@pytest.fixture(scope="session")
def html_src():
    with open(FIXTURE, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="session")
def recog():
    from songsterr_tab.glyphs import DigitRecognizer
    return DigitRecognizer.load(TEMPLATES)


@pytest.fixture(scope="session")
def recovery(html_src, recog):
    from songsterr_tab.notes import recover
    return recover(html_src, recog)
