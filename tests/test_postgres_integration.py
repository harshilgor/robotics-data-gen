"""Opt-in real database verification; never use a database containing user data."""
import os
import unittest


@unittest.skipUnless(os.environ.get("ROBOTICS_TEST_POSTGRES_DSN"), "no disposable PostgreSQL test database configured")
class PostgresIntegrationTests(unittest.TestCase):
    def test_real_governed_sampler_and_reopen(self):
        from data.postgres import PostgresStore
        from curriculum_sampler.synthetic import setup
        store = PostgresStore(os.environ["ROBOTICS_TEST_POSTGRES_DSN"])
        try:
            repo, library, sampler, scheduler, directive = setup(store)
            batch = sampler.sample(directive, now=0.)
            self.assertEqual(batch["shortfall"], 0)
            self.assertEqual(len(batch["assignments"]), 8)
        finally:
            store.close()
        store = PostgresStore(os.environ["ROBOTICS_TEST_POSTGRES_DSN"])
        try:
            repo, library, sampler, scheduler, directive = setup(store)
            self.assertEqual(batch, sampler.sample(directive, now=0.))
        finally:
            store.close()
