"""Check the 53-section evidence ledger against source and test discovery.

This validates traceability; it does not substitute file presence for tests or
certify simulator behavior. Run the regression suite separately.
"""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def verify():
    ledger = json.loads((ROOT / 'architecture-verification.json').read_text(encoding='utf-8'))
    headings = {int(n): title.strip() for n, title in re.findall(
        r'^# (\d+)\. (.+)$', (ROOT / 'original-architecture.md').read_text(encoding='utf-8'), re.M)}
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    tests = {'tests.' + name if not name.startswith('tests.') else name for name in test_ids(suite)}
    assert not any('_FailedTest' in name for name in tests), 'test discovery failed'
    rows = ledger['sections']
    assert [r['section'] for r in rows] == list(range(1, 54)), 'exactly 53 ordered sections required'
    for row in rows:
        assert row['title'] == headings[row['section']], row['section']
        assert row['status'] in ('implemented_synthetic', 'deferred_isaac', 'external_validation'), row['section']
        for path in row['implementation']:
            assert (ROOT / path).is_file(), path
        for test in row['tests']:
            assert test in tests, test
        assert row['scope'], row['section']
    return {'sections': len(rows), 'discovered_tests': len(tests),
            'status_counts': {s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})},
            'notice': 'Evidence references verified; run tests independently. Deferred sections prevent whole-architecture certification.'}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
