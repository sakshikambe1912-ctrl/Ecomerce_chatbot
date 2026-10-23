"""
Print how close each product is (cosine distance) to one or more queries.

    python manage.py semantic_probe "something to read on the beach" "sofa" --website-id 1

Smaller is closer. Use it to see where relevant products stop and unrelated ones
start for YOUR embeddings, then set SEMANTIC_MARGIN / SEMANTIC_MAX_DISTANCE in .env.
"""
from django.core.management.base import BaseCommand

from assistant.services.semantic_search_service import SemanticSearchService


class Command(BaseCommand):
    help = "Show cosine distances between queries and products."

    def add_arguments(self, parser):
        parser.add_argument("queries", nargs="+")
        parser.add_argument("--website-id", type=int, action="append", dest="website_ids")
        parser.add_argument("--top", type=int, default=8)

    def handle(self, *args, **options):
        service = SemanticSearchService()
        for query in options["queries"]:
            scored = service.search_scored(query, options["website_ids"], limit=options["top"])
            self.stdout.write(f"\n{query!r}")
            for product, distance in scored:
                self.stdout.write(f"  {distance:.3f}  {product['title'][:70]}")
