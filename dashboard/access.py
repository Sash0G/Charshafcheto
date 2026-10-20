from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.urls import reverse

PAGE_SIZE = 25


def _check(request, superuser=False):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), reverse("accounts:login"))
    if not request.user.is_staff or (superuser and not request.user.is_superuser):
        raise PermissionDenied
    return None


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        return _check(request) or view(request, *args, **kwargs)

    return wrapper


def superuser_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        return _check(request, superuser=True) or view(request, *args, **kwargs)

    return wrapper


class StaffRequiredMixin:
    superuser_only = False

    def dispatch(self, request, *args, **kwargs):
        return _check(request, self.superuser_only) or super().dispatch(request, *args, **kwargs)


def paginate(request, queryset, per_page=PAGE_SIZE):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def safe_next(request, default):
    """Redirect target from ?next / POST next, restricted to this host."""
    from django.shortcuts import resolve_url
    from django.utils.http import url_has_allowed_host_and_scheme

    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return target
    return resolve_url(default)
