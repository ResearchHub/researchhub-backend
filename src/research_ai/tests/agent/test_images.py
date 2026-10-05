"""Unit tests for resolving image references into request bytes."""

from unittest import TestCase

from research_ai.services.agent.images import (
    MAX_IMAGE_SIDE_PX,
    ImageUnavailableError,
    image_placeholder,
    load_image,
)
from research_ai.services.agent.types import ImageBlock
from research_ai.tests.agent.image_test_helpers import JPEG, image_bytes

PAGE = ImageBlock(ref="files/1/page-1.jpg", media_type="image/jpeg", label="page 1")
LOGGER = "research_ai.services.agent.images"
MAX_BYTES = 10_000


def _loader(data=JPEG):
    return lambda ref: data


class LoadImageTests(TestCase):
    def test_the_loader_supplies_the_bytes_for_the_reference(self):
        # Arrange
        asked = []

        def loader(ref):
            asked.append(ref)
            return JPEG

        # Act
        data = load_image(PAGE, loader=loader, vision=True, max_bytes=MAX_BYTES)

        # Assert
        self.assertEqual(data, JPEG)
        self.assertEqual(asked, ["files/1/page-1.jpg"])

    def test_a_model_without_vision_never_loads_the_image(self):
        # Arrange
        def loader(ref):
            raise AssertionError("must not load")

        # Act
        data = load_image(PAGE, loader=loader, vision=False, max_bytes=MAX_BYTES)

        # Assert
        self.assertIsNone(data)

    def test_no_loader_means_no_image(self):
        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            data = load_image(PAGE, loader=None, vision=True, max_bytes=MAX_BYTES)

        # Assert
        self.assertIsNone(data)

    def test_an_image_that_is_gone_becomes_a_placeholder(self):
        # Arrange
        def loader(ref):
            raise ImageUnavailableError(ref)

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            data = load_image(PAGE, loader=loader, vision=True, max_bytes=MAX_BYTES)

        # Assert
        self.assertIsNone(data)

    def test_any_other_loader_failure_propagates(self):
        # Arrange
        def loader(ref):
            raise TimeoutError("storage is slow")

        # Act / Assert
        with self.assertRaises(TimeoutError):
            load_image(PAGE, loader=loader, vision=True, max_bytes=MAX_BYTES)

    def test_an_oversized_or_unsupported_image_is_not_sent(self):
        # Arrange
        tiff = ImageBlock(ref="files/1/scan.tiff", media_type="image/tiff")

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            too_big = load_image(PAGE, loader=_loader(), vision=True, max_bytes=5)
            unsupported = load_image(
                tiff, loader=_loader(), vision=True, max_bytes=MAX_BYTES
            )

        # Assert
        self.assertIsNone(too_big)
        self.assertIsNone(unsupported)

    def test_the_placeholder_names_the_image_when_it_has_a_label(self):
        # Act / Assert
        self.assertEqual(image_placeholder(PAGE), "[Image not shown: page 1]")
        self.assertEqual(
            image_placeholder(ImageBlock(ref="x", media_type="image/png")),
            "[Image not shown]",
        )

    def test_bytes_that_do_not_match_the_declared_type_are_not_sent(self):
        # Arrange
        png = ImageBlock(ref="files/1/page-1.png", media_type="image/png")

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            data = load_image(
                png, loader=_loader(JPEG), vision=True, max_bytes=MAX_BYTES
            )

        # Assert
        self.assertIsNone(data)

    def test_bytes_that_only_start_like_the_declared_type_are_not_sent(self):
        # Arrange
        loader = _loader(b"\xff\xd8\xff-not-a-jpeg")

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            data = load_image(PAGE, loader=loader, vision=True, max_bytes=MAX_BYTES)

        # Assert
        self.assertIsNone(data)

    def test_an_image_wider_or_taller_than_providers_take_is_not_sent(self):
        # Arrange: a few hundred bytes, so only its dimensions rule it out.
        png = ImageBlock(ref="files/1/strip.png", media_type="image/png")
        over = MAX_IMAGE_SIDE_PX + 1

        for size in ((over, 1), (1, over)):
            data = image_bytes("PNG", size)
            self.assertLess(len(data), MAX_BYTES)

            # Act
            with self.assertLogs(LOGGER, "WARNING"):
                sent = load_image(
                    png, loader=_loader(data), vision=True, max_bytes=MAX_BYTES
                )

            # Assert
            self.assertIsNone(sent)

    def test_an_image_at_the_dimension_limit_is_sent(self):
        # Arrange
        png = ImageBlock(ref="files/1/strip.png", media_type="image/png")
        data = image_bytes("PNG", (MAX_IMAGE_SIDE_PX, 1))

        # Act
        sent = load_image(png, loader=_loader(data), vision=True, max_bytes=MAX_BYTES)

        # Assert
        self.assertEqual(sent, data)

    def test_every_supported_type_is_read(self):
        # Arrange
        samples = {
            "image/jpeg": JPEG,
            "image/png": image_bytes("PNG"),
            "image/gif": image_bytes("GIF"),
            "image/webp": image_bytes("WEBP"),
        }

        for media_type, sample in samples.items():
            # Act
            data = load_image(
                ImageBlock(ref="x", media_type=media_type),
                loader=_loader(sample),
                vision=True,
                max_bytes=MAX_BYTES,
            )

            # Assert
            self.assertEqual(data, sample)
