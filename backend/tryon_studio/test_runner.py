"""Test runner: tests never reach the network and never share the real Redis cache.

Any real httpx request (sync or async) raises, so a test that forgets `httpx.MockTransport` fails loudly
instead of calling Gemini. MockTransport does not go through these transports, so mocked calls still work.
"""
import httpx
from django.test import override_settings
from django.test.runner import DiscoverRunner


class RealHTTPBlocked(AssertionError):
    pass


def _blocked(self, request):
    raise RealHTTPBlocked(f"real HTTP call blocked in tests: {request.method} {request.url.host}")


class NoNetworkTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._saved = (httpx.HTTPTransport.handle_request, httpx.AsyncHTTPTransport.handle_async_request)
        httpx.HTTPTransport.handle_request = _blocked
        httpx.AsyncHTTPTransport.handle_async_request = _blocked
        self._cache = override_settings(CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests"},
        })
        self._cache.enable()

    def teardown_test_environment(self, **kwargs):
        self._cache.disable()
        httpx.HTTPTransport.handle_request, httpx.AsyncHTTPTransport.handle_async_request = self._saved
        super().teardown_test_environment(**kwargs)
