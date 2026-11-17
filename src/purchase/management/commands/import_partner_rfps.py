"""Import a finalized topic CSV and export the partner's catalog metadata."""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from purchase.services.partner_rfp_catalog import read_catalog
from purchase.services.partner_rfp_import_service import PartnerRfpImportService
from user.models import User


class Command(BaseCommand):
    help = "Import partner RFPs, excluded from feeds. Defaults to validation only."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=Path)
        parser.add_argument("--partner-organization", required=True)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true")
        mode.add_argument("--export-only", action="store_true")
        parser.add_argument("--owner-id", type=int)
        parser.add_argument("--owner-email", help="Verify the ID belongs to this email")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--public", action="store_true")
        parser.add_argument("--organization", default="")
        parser.add_argument("--grant-amount", type=str, default="0.00")
        parser.add_argument("--generate-images", action="store_true")
        parser.add_argument("--require-images", action="store_true")
        parser.add_argument("--limit", type=int, help="Pilot: first N CSV topics")

    def handle(self, *args, **options):
        try:
            self._run(options)
        except (ValueError, OSError, InvalidOperation) as error:
            raise CommandError(str(error)) from error

    def _run(self, options):
        if options["output"] is not None:
            options["output"] = Path(options["output"])
        topics = read_catalog(
            options["csv_path"],
            partner_organization=options["partner_organization"],
        )
        if options["limit"] is not None:
            if options["limit"] < 1:
                raise ValueError("--limit must be positive")
            topics = topics[: options["limit"]]
            self.stdout.write("PILOT: output contains only the selected CSV topics")
        amount = Decimal(options["grant_amount"])
        if (
            not amount.is_finite()
            or amount < 0
            or amount >= Decimal("1e17")
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise ValueError("--grant-amount must be nonnegative USD with <=2 decimals")
        if len(options["organization"]) > 255:
            raise ValueError("--organization must be at most 255 characters")
        self.stdout.write(
            f"Validated {len(topics)} RFPs for {options['partner_organization']}."
        )
        for topic in topics:
            if topic.research_flag:
                self.stdout.write(
                    f"RESEARCH FLAG — {topic.topic}: {topic.research_flag}"
                )
        if not options["apply"] and not options["export_only"]:
            self.stdout.write(
                "DRY RUN: no database writes, AI calls or catalog export. "
                "Use --apply with --owner-id and --output to import."
            )
            return
        if not options["owner_id"] or not options["output"]:
            raise ValueError("--owner-id and --output are required")
        if options["generate_images"] and not options["apply"]:
            raise ValueError("--generate-images requires --apply")
        if not options["output"].parent.is_dir():
            raise ValueError("--output parent directory must already exist")
        try:
            owner = User.objects.get(pk=options["owner_id"], is_active=True)
            owner.author_profile
        except (User.DoesNotExist, AttributeError) as error:
            raise ValueError(
                "Owner must be an active user with an author profile"
            ) from error
        service = PartnerRfpImportService(
            partner_organization=options["partner_organization"]
        )
        if (
            options["owner_email"]
            and owner.email.casefold() != options["owner_email"].casefold()
        ):
            raise ValueError("--owner-id does not match --owner-email")
        if options["apply"]:
            for index, topic in enumerate(topics, start=1):
                post, created = service.import_topic(
                    topic,
                    owner=owner,
                    is_public=options["public"],
                    grant_amount=amount,
                    organization=options["organization"],
                )
                self.stdout.write(
                    f"[{index}/{len(topics)}] {'Created' if created else 'Reused'} "
                    f"post {post.pk}: {topic.topic}"
                )
                if options["generate_images"]:
                    service.ensure_cover(post, topic)
        payload = service.export(
            topics,
            owner=owner,
            require_images=options["require_images"],
        )
        self._write_json(options["output"], payload)
        self.stdout.write(self.style.SUCCESS(f"Exported {len(payload['rfps'])} RFPs"))
        if options["apply"]:
            self.stdout.write(
                f"New grants use {amount:,.2f} USD and are open immediately."
            )

    @staticmethod
    def _write_json(path, payload):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
