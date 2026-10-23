from django.core.management.base import BaseCommand

from products.models import Product
from assistant.models import ProductEmbedding
from assistant.services.product_embedding_service import (
    ProductEmbeddingService,
)


class Command(BaseCommand):
    help = "Generate or refresh embeddings for product records."

    def add_arguments(self, parser):
        parser.add_argument("--website-id", type=int, default=None)
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        website_id = options["website_id"]
        batch_size = options["batch_size"]
        force = options["force"]

        if batch_size < 1:
            self.stderr.write(
                self.style.ERROR("Batch size must be greater than zero.")
            )
            return

        queryset = Product.objects.all().order_by("id")

        if website_id is not None:
            queryset = queryset.filter(website_id=website_id)

        total = queryset.count()

        if total == 0:
            self.stdout.write("No products found.")
            return

        service = ProductEmbeddingService()

        processed = 0
        generated = 0
        reused = 0
        failed = 0

        self.stdout.write(f"Found {total} products.")

        for start in range(0, total, batch_size):
            product_ids = list(
                queryset.values_list("id", flat=True)[
                    start : start + batch_size
                ]
            )

            products = Product.objects.filter(
                id__in=product_ids
            ).select_related("website").order_by("id")

            for product in products:
                processed += 1

                try:
                    product_text = service.product_text_service.build_product_text(
                        product
                    )

                    import hashlib

                    source_hash = hashlib.sha256(
                        product_text.encode("utf-8")
                    ).hexdigest()

                    existing = ProductEmbedding.objects.filter(
                        product=product
                    ).first()

                    can_reuse = (
                        existing is not None
                        and existing.source_text_hash == source_hash
                        and existing.embedding_model == service.embedding_service.model
                        and not force
                    )

                    service.generate_for_product(
                        product,
                        force=force,
                    )

                    if can_reuse:
                        reused += 1
                    else:
                        generated += 1

                    self.stdout.write(
                        f"[{processed}/{total}] Product {product.id}: "
                        f"{'reused' if can_reuse else 'generated'}"
                    )

                except Exception as exc:
                    failed += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Product {product.id} failed: {exc}"
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Finished. Processed: {processed}; "
                f"Generated/updated: {generated}; "
                f"Reused: {reused}; Failed: {failed}."
            )
        )