"""Agent.tenant says which tenant the agent works in, also when it comes from the
environment (CROWKIS_TENANT) or from the client given. It used to read None then, though
every command already went to the right tenant through the client."""
import os
import unittest
from unittest import mock

from crowkis import Agent, CrowkisClient


class AgentTenantTests(unittest.TestCase):
    def test_the_tenant_from_the_environment_is_shown(self):
        with mock.patch.dict(os.environ, {"CROWKIS_TENANT": "acme"}):
            self.assertEqual(Agent("support").tenant, "acme")

    def test_the_tenant_of_a_given_client_is_shown(self):
        self.assertEqual(Agent("support", client=CrowkisClient(tenant="globex")).tenant, "globex")

    def test_must_still_work_an_explicit_tenant_wins_and_none_stays_none(self):
        with mock.patch.dict(os.environ, {"CROWKIS_TENANT": "acme"}):
            self.assertEqual(Agent("support", tenant="initech").tenant, "initech")
        self.assertIsNone(Agent("support").tenant)


if __name__ == "__main__":
    unittest.main()
