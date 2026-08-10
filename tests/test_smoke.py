"""Phase 0 smoke test — always passes to prove the test harness works.

Implemented as a ``unittest.TestCase`` so it runs under both::

    python -m pytest tests/ -q
    python -m unittest tests.test_smoke -v
"""

import unittest


class SmokeTest(unittest.TestCase):
    def test_harness_works(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
