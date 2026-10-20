import random
import secrets
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Address, User
from catalog.models import Category, Product, ProductImage, ProductVariant, Review, Supplier
from core.models import Page, SiteSettings
from orders.models import Coupon, Order, OrderEvent, OrderItem, ShippingMethod

IMG_DIR = Path(settings.BASE_DIR) / "static" / "img" / "products"

CATEGORIES = [
    ("Спални комплекти", "Стил и уют в хармония", "zornitsa.svg"),
    ("Чаршафи", "За спокоен и качествен сън", "sheet.svg"),
    ("Калъфки", "Малки детайли, голяма разлика", "pillows.svg"),
    ("Завивки", "Топлина през всички сезони", "duvet.svg"),
]

SET_SIZES = [("200 × 230 см", None), ("150 × 220 см", Decimal("-5.00"))]

PRODUCTS = [
    # name, category, price, old price, cost, stock, badge, image, material, pieces, color, desc, featured, supplier
    ("Спален комплект „Зорница“", 0, "35.90", None, "17.50", 18, "Най-продаван", "zornitsa.svg", "100% памук", "6 части",
     "Бяло / зелено", "Мек и дишащ спален комплект с фина флорална орнаментика, вдъхновена от българската природа.", True, 0),
    ("Спален комплект „Маслина“", 0, "30.90", None, "14.90", 11, "", "maslina.svg", "100% памук", "6 части",
     "Крем / маслина", "Естествени тонове, чиста линия и мек памук за спокойна и уютна спалня.", True, 0),
    ("Спален комплект „Родопска шевица“", 0, "37.90", None, "18.90", 7, "Ново", "rodopi.svg", "90% памук / 10% сатен",
     "6 части", "Бяло / червено / зелено",
     "Модерен комплект с фолклорен акцент и декоративен мотив, вдъхновен от традиционната шевица.", True, 0),
    ("Спален комплект „Пролетен цвят“", 0, "33.90", None, "16.20", 22, "", "prolet.svg", "100% памук", "6 части",
     "Розово / зелено", "Свеж флорален комплект за по-светла и жизнерадостна спалня.", True, 1),
    ("Спален комплект „Син хоризонт“", 0, "30.90", "38.90", "14.50", 9, "", "sin.svg", "100% памук", "6 части",
     "Синьо / бяло", "Спокойни сини нюанси и минималистичен дизайн за съвременен интериор.", False, 1),
    ("Чаршаф „Горска мъгла“", 1, "15.90", None, "6.90", 31, "", "sheet.svg", "Ранфорс", "1 част", "Зелено",
     "Плътен и мек чаршаф без ластик, подходящ за целогодишна употреба.", False, 0),
    ("Комплект калъфки „Шевица“", 2, "12.90", None, "5.40", 25, "", "pillows.svg", "Памук-сатен", "2 части",
     "Бяло / червено", "Две декоративни калъфки с деликатен етно мотив.", False, 0),
    ("Олекотена завивка „Облак“", 3, "40.90", None, "21.00", 14, "", "duvet.svg", "Микрофибър", "1 част", "Бяло",
     "Лека, пухкава и удобна завивка, подходяща за всички сезони.", False, 1),
]

SIZES_BY_CATEGORY = {
    1: [("220 × 240 см", None), ("160 × 240 см", Decimal("-3.00"))],
    2: [("50 × 70 см", None), ("70 × 70 см", Decimal("2.00"))],
    3: [("200 × 220 см", None), ("140 × 200 см", Decimal("-8.00"))],
}

REVIEWS = [
    ("Мария Петрова", 5, "Страхотно качество", "Страхотно качество и много красиви дизайни. Спалното бельо е меко и уютно."),
    ("Иван Димитров", 5, "Бърза доставка", "Бърза доставка, отлично обслужване и наистина качествени продукти."),
    ("Елена Георгиева", 5, "Уютен рай", "Чаршафчето превърна спалнята ни в истински уютен рай."),
    ("Николай Стоянов", 4, "Добро съотношение", "Много добро съотношение цена-качество. Цветовете са точно като на снимките."),
]

PAGES = [
    ("Доставка", "dostavka", """<h2>Срокове и цени</h2>
<p>Доставяме до всяка точка в България със Speedy и Econt. Поръчките се обработват в рамките на 1 работен ден и пристигат за <strong>2–4 работни дни</strong>.</p>
<ul><li>До офис на Speedy или Econt — 3,50 €</li><li>До адрес — 5,50 €</li><li>Безплатна доставка за поръчки над прага, обявен на сайта.</li></ul>
<p>След изпращане ще получите имейл с номер на товарителницата, с който можете да проследите пратката.</p>"""),
    ("Връщане и рекламации", "vrashtane", """<h2>14 дни право на отказ</h2>
<p>Съгласно Закона за защита на потребителите имате право да се откажете от поръчката в срок от 14 дни от получаването ѝ, без да посочвате причина.</p>
<p>Продуктите трябва да бъдат неизползвани, в оригиналната си опаковка. Свържете се с нас на посочения имейл с номера на поръчката.</p>
<h2>Рекламации</h2><p>При дефект или несъответствие свържете се с нас до 14 дни — ще заменим продукта или ще възстановим сумата.</p>"""),
    ("Общи условия", "obshti-usloviya", """<h2>Общи условия за ползване</h2>
<p>Настоящите общи условия уреждат отношенията между търговеца и потребителите на онлайн магазина. <em>Заменете този текст с вашите реални общи условия, изготвени от юрист.</em></p>"""),
    ("Политика за поверителност", "poveritelnost", """<h2>Защита на личните данни (GDPR)</h2>
<p>Обработваме личните ви данни само за изпълнение на поръчките и по закон. Можете по всяко време да изтеглите или изтриете данните си от профила си.</p>
<p><em>Заменете този текст с вашата реална политика за поверителност.</em></p>"""),
    ("Бисквитки", "biskvitki", """<h2>Политика за бисквитките</h2>
<p>Използваме само необходими бисквитки — за количката, влизането в профила и защитата на формите. Не използваме рекламни бисквитки без вашето съгласие.</p>"""),
    ("За нас", "za-nas", """<h2>Повече уют в живота</h2>
<p>Чаршафчето е български онлайн магазин за спално бельо и текстил за дома. Подбираме продукти с внимание към материите, детайлите и традициите.</p>"""),
]


class Command(BaseCommand):
    help = "Populate the database with the demo catalog from the prototype."

    def add_arguments(self, parser):
        parser.add_argument("--admin-email", default="admin@charshafcheto.bg")
        parser.add_argument("--admin-password", default=None)
        parser.add_argument("--no-orders", action="store_true", help="Skip demo orders and customers.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if Product.objects.exists():
            self.stdout.write(self.style.WARNING("Каталогът вече съдържа продукти — пропускам."))
            return

        SiteSettings.load().save()

        suppliers = [
            Supplier.objects.create(
                name="Текстил Габрово ООД", contact_person="Петър Колев", email="orders@textil-gabrovo.example",
                phone="066 800 100", processing_days=1, notes="Основен доставчик на спално бельо.",
            ),
            Supplier.objects.create(
                name="HomeTex Import", contact_person="Анна Маринова", email="dropship@hometex.example",
                phone="02 900 2020", processing_days=2,
            ),
        ]

        categories = []
        for i, (name, tagline, img) in enumerate(CATEGORIES):
            cat = Category(name=name, tagline=tagline, position=i)
            with open(IMG_DIR / img, "rb") as fh:
                cat.image.save(f"cat-{img}", File(fh), save=False)
            cat.save()
            categories.append(cat)

        products = []
        for idx, row in enumerate(PRODUCTS):
            (name, cat_i, price, old, cost, stock, badge, img, material, pieces, color, desc, featured, sup_i) = row
            p = Product.objects.create(
                name=name, category=categories[cat_i], supplier=suppliers[sup_i], sku=f"CH-{1001 + idx}",
                price=Decimal(price), compare_at_price=Decimal(old) if old else None, cost_price=Decimal(cost),
                badge=badge, material=material, pieces=pieces, color=color, short_description=desc,
                description=f"<p>{desc}</p><p>Изработен от внимателно подбрани материи, които запазват формата и цвета си след многократно пране.</p>",
                is_featured=featured, sales_count=random.randint(20, 140),
            )
            pimg = ProductImage(product=p, alt=name)
            with open(IMG_DIR / img, "rb") as fh:
                pimg.image.save(img, File(fh), save=False)
            pimg.save()
            for pos, (size, delta) in enumerate(SIZES_BY_CATEGORY.get(cat_i, SET_SIZES)):
                ProductVariant.objects.create(
                    product=p, name=size, position=pos, sku=f"{p.sku}-{pos + 1}", supplier_sku=f"SUP-{idx + 1:03d}{pos}",
                    price_override=(p.price + delta) if delta else None,
                    cost_override=(p.cost_price + delta / 2) if delta else None,
                    stock=stock if pos == 0 else max(2, stock // 2),
                )
            products.append(p)

        ShippingMethod.objects.bulk_create([
            ShippingMethod(name="Speedy — до офис", carrier="Speedy", delivery_type="office", price=Decimal("3.50"), position=0),
            ShippingMethod(name="Econt — до офис", carrier="Econt", delivery_type="office", price=Decimal("3.50"), position=1),
            ShippingMethod(name="Speedy — до адрес", carrier="Speedy", delivery_type="address", price=Decimal("5.50"),
                           estimated_days="1–3 работни дни", position=2),
        ])
        Coupon.objects.create(code="WELCOME10", description="10% отстъпка за първа поръчка",
                              discount_type=Coupon.TYPE_PERCENT, value=10, first_order_only=True)
        Coupon.objects.create(code="FREEDELIVERY", description="Безплатна доставка над 30 €",
                              discount_type=Coupon.TYPE_FREE_SHIPPING, min_order_total=30)

        for i, (title, slug, body) in enumerate(PAGES):
            Page.objects.create(title=title, slug=slug, body=body, order=i, show_in_footer=slug != "za-nas")

        password = opts["admin_password"] or secrets.token_urlsafe(10)
        admin, created = User.objects.get_or_create(
            email=opts["admin_email"], defaults={"first_name": "Администратор", "is_staff": True, "is_superuser": True, "email_verified": True}
        )
        if created:
            admin.set_password(password)
            admin.save()

        if not opts["no_orders"]:
            self._demo_customers_and_orders(products)

        for p, (name, rating, title, body) in zip(products, REVIEWS):
            Review.objects.create(product=p, name=name, rating=rating, title=title, body=body,
                                  is_approved=True, is_verified=True)
        for p in products:
            p.refresh_rating()

        self.stdout.write(self.style.SUCCESS("Демо данните са заредени."))
        if created:
            self.stdout.write(f"Админ: {admin.email} / парола: {password}")

    def _demo_customers_and_orders(self, products):
        people = [
            ("Мария", "Петрова", "maria@example.com", "0888 123 456", "София", "бул. България 100"),
            ("Иван", "Димитров", "ivan@example.com", "0899 221 442", "Пловдив", "ул. Капитан Райчо 12"),
            ("Елена", "Георгиева", "elena@example.com", "0877 555 610", "Варна", "ул. Мусала 5"),
            ("Николай", "Стоянов", "nikolay@example.com", "0887 111 222", "Бургас", "ул. Александровска 40"),
        ]
        users = []
        for first, last, email, phone, city, line1 in people:
            u = User.objects.create_user(email=email, password="demo-pass-123", first_name=first, last_name=last, phone=phone,
                                         email_verified=True)
            Address.objects.create(user=u, full_name=f"{first} {last}", phone=phone, city=city, line1=line1, is_default=True)
            users.append(u)

        methods = list(ShippingMethod.objects.all())
        statuses = [Order.STATUS_DELIVERED] * 6 + [Order.STATUS_SHIPPED] * 3 + [Order.STATUS_CONFIRMED] * 2 + [
            Order.STATUS_NEW] * 3 + [Order.STATUS_CANCELLED]
        now = timezone.now()
        rng = random.Random(42)
        for n in range(28):
            u = users[n % len(users)]
            method = methods[n % len(methods)]
            status = statuses[n % len(statuses)] if n > 3 else Order.STATUS_NEW
            created = now - timedelta(days=rng.randint(0, 29) if n > 3 else 0, hours=rng.randint(0, 20))
            picks = rng.sample(products, rng.randint(1, 3))
            lines = [(p, p.variants.first(), rng.randint(1, 2)) for p in picks]
            subtotal = sum((v.price * q for _, v, q in lines), Decimal("0"))
            shipping = method.cost_for(subtotal, Decimal("50"))
            addr = u.addresses.first()
            order = Order.objects.create(
                user=u, email=u.email, phone=u.phone, full_name=u.get_full_name(), shipping_method=method,
                shipping_method_name=method.name, delivery_type=method.delivery_type, carrier=method.carrier,
                city=addr.city, address=addr.line1 if method.delivery_type == "address" else f"Офис {method.carrier} {addr.city} Център",
                payment_method=Order.PAYMENT_COD, status=status,
                payment_status=Order.PAY_PAID if status == Order.STATUS_DELIVERED else Order.PAY_UNPAID,
                subtotal=subtotal, shipping_total=shipping, total=subtotal + shipping,
                cost_total=sum((v.cost * q for _, v, q in lines), Decimal("0")),
                tracking_number=f"62{rng.randint(10**8, 10**9 - 1)}" if status in (Order.STATUS_SHIPPED, Order.STATUS_DELIVERED) else "",
                accepted_terms_at=created,
            )
            for p, v, q in lines:
                OrderItem.objects.create(order=order, product=p, variant=v, supplier=p.supplier, product_name=p.name,
                                         variant_name=v.name, sku=v.sku, supplier_sku=v.supplier_sku,
                                         unit_price=v.price, unit_cost=v.cost or 0, quantity=q)
            OrderEvent.objects.create(order=order, kind="status", message="Поръчката е създадена.", is_public=True)
            Order.objects.filter(pk=order.pk).update(created_at=created)
