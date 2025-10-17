from django.core.management.base import BaseCommand, CommandError


class OpenAlexLoaderBaseCommand(BaseCommand):
    """Base class for commands that pull data from OpenAlex."""

    _open_alex: object

    @property
    def open_alex(self):
        if not hasattr(self, "_open_alex"):
            from utils.openalex import OpenAlex

            self._open_alex = OpenAlex()

        return self._open_alex

    @property
    def model(self):
        raise CommandError("Subclasses must implement .model")

    @property
    def object_type(self):
        raise CommandError("Subclasses must implement .object_type")

    @property
    def _ot_plural(self):
        if self.object_type.endswith("s"):
            return self.object_type

        return f"{self.object_type}s"

    @property
    def _ot_singular(self):
        if self.object_type.endswith("s"):
            return self.object_type[:-1]

        return self.object_type

    def add_arguments(self, parser):
        parser.add_argument(
            "--page",
            default=1,
            type=int,
            help="Start at specific page number (default: 1)",
        )

        parser.add_argument(
            "--count",
            type=int,
            help="Limit the number of pages to process",
        )

        parser.add_argument(
            "--batch",
            default=100,
            type=int,
            help="Batch size (number of results) per page (default: 100)",
        )

    def handle(self, *args, **kwargs):
        cursor = "*"
        pages_processed = 0

        self.stdout.write(f"Pulling {self._ot_plural} from OpenAlex")

        try:
            while cursor:
                if kwargs["count"] and pages_processed >= kwargs["count"]:
                    self.stdout.write(
                        f"Specified page limit of {kwargs['count']} reached, stopping."
                    )

                    break

                self.stdout.write(f"Processing page {kwargs['page']}")

                processed_any = False

                entities, cursor = self.open_alex.get_paginated_entities(
                    object_type=self._ot_plural,
                    next_cursor=cursor,
                    page=kwargs["page"],
                    batch_size=kwargs["batch"],
                )

                for entity in entities:
                    try:
                        self.model.upsert_from_openalex(entity)

                        processed_any = True

                    except Exception as e:
                        self.stdout.write(
                            f"Failed to create {self._ot_singular}: {entity['id']}\n"
                            f"Page: {kwargs['page']}\n\nException:\n{e}"
                        )

                kwargs["page"] += 1

                if processed_any:
                    pages_processed += 1

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopped by user"))


class TeeStream:
    """A stream that writes to multiple targets simultaneously (like Unix 'tee')"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            if hasattr(stream, "flush"):
                stream.flush()
