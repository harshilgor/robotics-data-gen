"""Semantic proposals must traverse discovery, not only direct publication."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from semantics import default_registry
from taskgen.core import fingerprint
from taskgen.discovery import TaskDiscovery
from taskgen.proposals import FixtureProposalProvider
from tests.test_semantics import semantic_task


class SemanticDiscoveryTests(unittest.TestCase):
    def test_semantic_proposal_lowered_before_capability_and_parameter_checks(self):
        registry = default_registry()
        source = semantic_task(registry)
        target = {'capabilities': ['insert'], 'parameters': {}}
        lookup = {'generation_requests': [{'target': target}]}
        published = []
        records = []
        class Library:
            def resolve_directive(self, directive): return lookup
            def search(self): return []
        class Repo:
            db = None
            def put(self, kind, identity, value): records.append(value)
        def publish(task, source):
            published.append(task)
            return {'contract': {'family_id': 'semantic-family', 'family_version': '1.0.0'}}
        factory = SimpleNamespace(library=Library(), repo=Repo(), publish=publish,
            compiler=SimpleNamespace(semantics=registry, resources=registry))
        directive = {'targets': [target]}
        directive['directive_id'] = fingerprint(directive)
        from contextlib import nullcontext
        with patch('taskgen.discovery.coverage_bootstrap', return_value=[]), \
             patch('taskgen.discovery.transaction', return_value=nullcontext()):
            result = TaskDiscovery(factory, proposals=FixtureProposalProvider({'tasks': [source]})).resolve(directive)
        self.assertEqual(len(result['accepted']), 1, result['rejected'])
        self.assertEqual(published[0]['schema_version'], '1.3')
        self.assertEqual(published[0]['semantic'], source)
        self.assertEqual(len(records), 1)
