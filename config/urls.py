from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from operations.forms import ThrottledAuthenticationForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuenta/ingresar/", auth_views.LoginView.as_view(
        authentication_form=ThrottledAuthenticationForm), name="login"),
    path("cuenta/salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("operations.urls")),
]
