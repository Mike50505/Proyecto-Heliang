import os
from pathlib import Path
import runpy
from unittest.mock import patch

from django.core.exceptions import DisallowedHost, ImproperlyConfigured
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.test import RequestFactory, SimpleTestCase, override_settings


class DeploymentSettingsTests(SimpleTestCase):
    def read_settings(self, **environment):
        path = Path(__file__).resolve().parents[1] / "config" / "settings.py"
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(path))

    def test_local_defaults_remain_available(self):
        config = self.read_settings()
        self.assertTrue(config["DEBUG"])
        self.assertEqual(config["ALLOWED_HOSTS"], ["localhost", "127.0.0.1"])
        self.assertEqual(config["CSRF_TRUSTED_ORIGINS"], [])

    def test_configured_hosts_allow_lan_and_tailscale_but_reject_others(self):
        config = self.read_settings(
            DJANGO_ALLOWED_HOSTS=" localhost,127.0.0.1, 100.90.206.74,192.168.1.20, ,",
            DJANGO_DEBUG="false", DJANGO_SECRET_KEY="test-only-private-key")
        self.assertFalse(config["DEBUG"])
        self.assertEqual(len(config["ALLOWED_HOSTS"]), 4)
        with override_settings(ALLOWED_HOSTS=config["ALLOWED_HOSTS"], DEBUG=False):
            for host in config["ALLOWED_HOSTS"]:
                request = RequestFactory().get("/", HTTP_HOST=f"{host}:8000")
                self.assertEqual(request.get_host(), f"{host}:8000")
            with self.assertRaises(DisallowedHost):
                RequestFactory().get("/", HTTP_HOST="untrusted.example:8000").get_host()

    def test_debug_boolean_values(self):
        for value in ("1", "true", " TRUE ", "yes", "on"):
            self.assertTrue(self.read_settings(DJANGO_DEBUG=value)["DEBUG"])
        for value in ("0", "false", " FALSE ", "no", "off"):
            self.assertFalse(self.read_settings(
                DJANGO_DEBUG=value, DJANGO_SECRET_KEY="test-only-private-key")["DEBUG"])
        with self.assertRaises(ImproperlyConfigured):
            self.read_settings(DJANGO_DEBUG="maybe")

    def test_wildcard_and_production_default_secrets_are_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            self.read_settings(DJANGO_ALLOWED_HOSTS="localhost, *")
        for value in ("", "dev-only-change-me", "local-only-change-me"):
            with self.assertRaises(ImproperlyConfigured):
                self.read_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY=value)

    def test_optional_csrf_origins_are_trimmed(self):
        config = self.read_settings(
            DJANGO_CSRF_TRUSTED_ORIGINS=" https://produccion.example.com, ,https://app.example.com:8443,")
        self.assertEqual(config["CSRF_TRUSTED_ORIGINS"], [
            "https://produccion.example.com", "https://app.example.com:8443"])

    @override_settings(ALLOWED_HOSTS=["100.90.206.74"], CSRF_TRUSTED_ORIGINS=[])
    def test_tailscale_same_origin_post_passes_csrf_and_foreign_origin_does_not(self):
        def view(request):
            return HttpResponse("ok")

        for origin, expected in (("http://100.90.206.74:8000", None),
                                 ("https://untrusted.example", 403)):
            request = RequestFactory().post("/", HTTP_HOST="100.90.206.74:8000", HTTP_ORIGIN=origin)
            request.META["HTTP_X_CSRFTOKEN"] = get_token(request)
            request.COOKIES["csrftoken"] = request.META["CSRF_COOKIE"]
            middleware = CsrfViewMiddleware(view)
            middleware.process_request(request)
            response = middleware.process_view(request, view, (), {})
            if expected is None:
                self.assertIsNone(response)
            else:
                self.assertEqual(response.status_code, expected)
