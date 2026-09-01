from .access import access_for


def module_access(request):
    return {"module_access": access_for(request.user)}
