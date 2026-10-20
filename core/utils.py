from decimal import ROUND_HALF_UP, Decimal

from django.utils.text import slugify

# Official Bulgarian transliteration (Закон за транслитерацията, 2009).
_BG_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya",
}


def transliterate(text):
    out = []
    for ch in text:
        low = ch.lower()
        if low in _BG_LATIN:
            latin = _BG_LATIN[low]
            out.append(latin.capitalize() if ch != low else latin)
        else:
            out.append(ch)
    return "".join(out)


def latin_slugify(text):
    return slugify(transliterate(text)) or "item"


def unique_slug(instance, text, field="slug"):
    """Build a slug from `text` that is unique for the instance's model."""
    base = latin_slugify(text)[:200]
    slug, n = base, 2
    model = instance.__class__
    while model.objects.filter(**{field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def quantize(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")) or None


def safe_back(request, fallback="/"):
    """Return the `next` param or referer if it points to this site, else `fallback`."""
    from django.shortcuts import resolve_url
    from django.utils.http import url_has_allowed_host_and_scheme

    for candidate in (request.POST.get("next"), request.GET.get("next"), request.META.get("HTTP_REFERER")):
        if candidate and url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return candidate
    return resolve_url(fallback)
