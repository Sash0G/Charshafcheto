class SecurityHeadersMiddleware:
    """Extra security headers not covered by Django's SecurityMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(self)")
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.path.startswith(("/dashboard/", "/account/", "/checkout/")):
            response.setdefault("Cache-Control", "no-store")
        return response
