"""Plain helper functions that create test data. No third-party factory library."""
from decimal import Decimal
from itertools import count

from products.models import Product
from websites.models import Website

_ids = count(1)


def create_website(name, base_url=None, currency="USD", active=True, **extra):
    """Create a Website. `currency` is kept on the object for the catalog helpers."""
    website = Website.objects.create(
        name=name,
        base_url=base_url or f"https://{name.lower().replace(' ', '')}.example.com",
        is_active=active,
        **extra,
    )
    website.test_currency = currency
    return website


def create_product(website, **overrides):
    """Create a Product with sensible defaults; any field can be overridden."""
    n = next(_ids)
    data = {
        "external_product_id": f"ext-{n}",
        "title": f"Test product {n}",
        "brand": "",
        "category": "",
        "description": "",
        "price": Decimal("10.00"),
        "currency": getattr(website, "test_currency", "USD"),
        "rating": Decimal("4.0"),
        "review_count": 100,
        "is_available": True,
        "features": [],
        "specifications": {},
    }
    data.update(overrides)
    for key in ("price", "original_price", "rating"):
        if data.get(key) is not None and not isinstance(data[key], Decimal):
            data[key] = Decimal(str(data[key]))
    return Product.objects.create(website=website, **data)


def build_catalog():
    """
    Two websites (one USD, one INR) and about ten products.

    Returns a dict with the websites under "usd_site" / "inr_site" and each
    product under a short name.
    """
    usd = create_website("Alpha Store", currency="USD")
    inr = create_website("Beta Bazaar", currency="INR")

    c = {"usd_site": usd, "inr_site": inr}

    c["sony_xm5"] = create_product(
        usd,
        title="Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        brand="Sony", category="Audio", price="328.00", rating="4.7", review_count=5120,
        description="Premium over-ear headphones with industry-leading noise canceling.",
        features=["Industry-leading noise canceling", "Bluetooth wireless", "30-hour battery life"],
    )
    c["bose_qc"] = create_product(
        usd,
        title="Bose QuietComfort Headphones",
        brand="Bose", category="Audio", price="279.00", rating="4.6", review_count=3010,
        features=["Active noise cancellation", "Wireless", "24-hour battery"],
    )
    c["jbl_tune"] = create_product(
        usd,
        title="JBL Tune 510BT On-Ear Headphones",
        brand="JBL", category="Audio", price="39.95", rating="4.4", review_count=9800,
        features=["Bluetooth 5.0", "40-hour battery"],
    )
    c["sennheiser"] = create_product(
        usd,
        title="Sennheiser Momentum 4 Wireless Headphones",
        brand="Sennheiser", category="Audio", price="379.95", rating="4.5", review_count=870,
        features=["Adaptive noise cancellation", "60-hour battery"],
    )
    c["sony_noname"] = create_product(
        usd,
        title="Sony WH-CH520 Wireless Headphones",
        brand="", category="Audio", price="58.00", rating="4.3", review_count=2200,
        features=["Bluetooth wireless", "50-hour battery"],
    )
    c["unavailable"] = create_product(
        usd,
        title="Audio-Technica ATH-M50x Studio Headphones",
        brand="Audio-Technica", category="Audio", price="149.00", rating="4.8",
        is_available=False,
    )
    c["macbook"] = create_product(
        usd,
        title="Apple MacBook Air 13-inch Laptop with M3 chip",
        brand="Apple", category="Computers", price="1099.00", rating="4.8",
        features=["M3 chip", "18-hour battery"],
    )
    c["anker"] = create_product(
        usd,
        title="Anker 737 Power Bank (PowerCore 24K) Portable Charger",
        brand="Anker", category="Electronics", price="99.99", rating="4.5",
        features=["24,000mAh high capacity", "140W fast charging"],
    )
    c["boat"] = create_product(
        inr,
        title="boAt Rockerz 450 Bluetooth Headphones",
        brand="boAt", category="Audio", price="1499.00", rating="4.1",
        features=["Bluetooth wireless", "15-hour battery"],
    )
    c["sony_inr"] = create_product(
        inr,
        title="Sony WH-1000XM5 Noise Cancelling Headphones",
        brand="Sony", category="Headphones", price="29990.00", rating="4.7",
        features=["Noise cancelling", "Wireless"],
    )
    return c
