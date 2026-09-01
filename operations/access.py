from functools import wraps
from types import SimpleNamespace
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect


MODULES = ("program_loading", "heliang", "inventory", "surplus",
           "process_material", "reports", "line_dashboard")


def access_for(user):
    if not user.is_authenticated:
        return SimpleNamespace(**{name: False for name in MODULES})
    if user.is_superuser:
        return SimpleNamespace(**{name: True for name in MODULES})
    try:
        return user.module_access
    except ObjectDoesNotExist:
        return SimpleNamespace(**{name: False for name in MODULES})


def module_required(module):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if getattr(access_for(request.user), module, False):
                return view(request, *args, **kwargs)
            messages.error(request, "Tu cuenta no tiene acceso a este apartado. Solicítalo al administrador.")
            return redirect("dashboard")
        return wrapper
    return decorator
