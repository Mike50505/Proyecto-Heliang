from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from operations.models import (Client, Machine, ModuleAccess, Part, ProductionOrder,
                               WorkInProcess)


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
        self.assertEqual(self.client.get(reverse("progress-dashboard")).status_code, 200)

    def test_line_dashboards_require_their_own_access(self):
        self.assertRedirects(self.client.get(reverse("line-dashboard")), reverse("dashboard"))
        self.assertRedirects(self.client.get(reverse("progress-dashboard")), reverse("dashboard"))
        access = ModuleAccess.objects.get(user=self.user)
        access.line_dashboard = True
        access.save(update_fields=["line_dashboard"])
        response = self.client.get(reverse("line-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ESTADO DE LA LÍNEA")
        self.assertContains(response, "GRÁFICAS DE AVANCE")
        self.assertContains(response, "Abrir en pantalla completa")
        self.assertContains(response, 'allowfullscreen')
        self.assertEqual(self.client.get(reverse("progress-dashboard")).status_code, 200)

    def test_progress_dashboard_exposes_week_client_and_quantities(self):
        access = ModuleAccess.objects.get(user=self.user)
        access.line_dashboard = True
        access.save(update_fields=["line_dashboard"])
        customer = Client.objects.create(code="C-1", name="Cliente Uno")
        part = Part.objects.create(number="P-100", client=customer)
        ProductionOrder.objects.create(
            folio="O-1", program="S35", part=part,
            quantity=100, remaining_quantity=100,
        )

        response = self.client.get(reverse("progress-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modo pantalla")
        self.assertEqual(response.context["progress_data"], [{
            "folio": "O-1", "week": "S35", "client": "Cliente Uno",
            "part": "P-100", "programmed": 100.0, "completed": 0.0,
        }])

    def test_heliang_assign_button_preselects_order_and_balance(self):
        access = ModuleAccess.objects.get(user=self.user)
        access.heliang = True
        access.save(update_fields=["heliang"])
        customer = Client.objects.create(code="C-2", name="Cliente Dos")
        part = Part.objects.create(number="P-200", client=customer)
        order = ProductionOrder.objects.create(
            folio="O-2", program="S36", part=part,
            quantity=250, remaining_quantity=175,
        )

        response = self.client.get(f"{reverse('heliang')}?order={order.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_order"], order)
        self.assertEqual(response.context["start_form"].initial["order"], order)
        self.assertEqual(response.context["start_form"].initial["quantity"], 175)
        self.assertContains(response, "Asignar")
        self.assertContains(response, "Orden seleccionada")

        machine = Machine.objects.create(code="M-1")
        work = WorkInProcess.objects.create(
            folio="P-1", order=order, machine=machine,
            initial_quantity=175, remaining_quantity=80,
            started_at=timezone.now(),
        )
        close_response = self.client.get(f"{reverse('heliang')}?work={work.pk}")

        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(close_response.context["selected_work"], work)
        self.assertEqual(close_response.context["close_form"].initial["work_item"], work)
        self.assertEqual(close_response.context["close_form"].initial["quantity"], 80)
        self.assertContains(close_response, "Cerrar")
        self.assertContains(close_response, "Proceso seleccionado")
