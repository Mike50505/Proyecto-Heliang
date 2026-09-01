from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from operations.models import ModuleAccess


class ModuleAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("operator", password="secret")
        self.client.force_login(self.user)

    def test_operator_without_access_is_redirected(self):
        response = self.client.get(reverse("heliang"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_operator_can_only_see_enabled_module(self):
        access = ModuleAccess.objects.get(user=self.user)
        access.heliang = True
        access.save(update_fields=["heliang"])
        response = self.client.get(reverse("heliang"))
        self.assertEqual(response.status_code, 200)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Heliang · Máquinas automáticas")
        self.assertNotContains(dashboard, "Carga individual o masiva desde Excel")

    def test_superuser_has_all_modules_without_flags(self):
        admin = get_user_model().objects.create_superuser("root", "root@example.com", "secret")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("bulk-load-program")).status_code, 200)
        self.assertEqual(self.client.get(reverse("report")).status_code, 200)

    def test_line_dashboard_requires_its_own_access(self):
        self.assertRedirects(self.client.get(reverse("line-dashboard")), reverse("dashboard"))
        access = ModuleAccess.objects.get(user=self.user)
        access.line_dashboard = True
        access.save(update_fields=["line_dashboard"])
        response = self.client.get(reverse("line-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ESTADO DE LA LÍNEA")
