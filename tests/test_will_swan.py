import os
from fractions import Fraction

import pytest

from songsterr_tab.notes import recover

ROOT = os.path.dirname(os.path.dirname(__file__))
FIXTURE = os.path.join(ROOT, "fixtures", "will-swan.rendered.html")


@pytest.fixture(scope="module")
def ws(recog):
    if not os.path.exists(FIXTURE):
        pytest.skip("will-swan fixture not present")
    return recover(open(FIXTURE, encoding="utf-8").read(), recog)


def test_second_guitar_fully_validates(ws):
    checked = [m for m in ws.measures if m.rhythm_ok is not None]
    assert checked and all(m.rhythm_ok for m in checked)   # 83/83
    assert ws.unrecognized == 0


def test_quarter_and_half_rests_present(ws):
    durs = {b.duration for m in ws.measures for b in m.beats if b.is_rest}
    assert Fraction(1, 4) in durs        # quarter rest (narrow tall zig-zag)
    assert Fraction(1, 2) in durs        # half rest (wide short block)
