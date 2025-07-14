# tests/integration/conftest.py
# This file ensures that the plugins defined in pytest_plugins.py are only
# loaded for tests within the tests/integration/ directory.
# This prevents the integration-specific fixtures from interfering with
# other tests, such as the live_e2e tests.

pytest_plugins = [".pytest_plugins"]