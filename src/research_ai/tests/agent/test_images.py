"""Unit tests for resolving image references into request bytes."""

from unittest import TestCase

from research_ai.services.agent.images import (
    ImageUnavailableError,
    image_placeholder,
    load_image,
)
from research_ai.services.agent.types import ImageBlock

PAGE = ImageBlock(ref="files/1/page-1.jpg", media_type="image/jpeg", label="page 1")
LOGGER = "research_ai.services.agent.images"


JPEG = b"\xff\xd8\xff-jpeg"


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
        data = load_image(PAGE, loader=loader, vision=True, max_bytes=100)

        # Assert
        self.assertEqual(data, JPEG)
        self.assertEqual(asked, ["files/1/page-1.jpg"])

    def test_a_model_without_vision_never_loads_the_image(self):
        # Arrange
        def loader(ref):
            raise AssertionError("must not load")

        # Act
        data = load_image(PAGE, loader=loader, vision=False, max_bytes=100)

        # Assert
        self.assertIsNone(data)

    def test_no_loader_means_no_image(self):
        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            data = load_image(PAGE, loader=None, vision=True, max_bytes=100)

        # Assert
        self.assertIsNone(data)

    def test_an_image_that_is_gone_becomes_a_placeholder(self):
        # Arrange
        def loader(ref):
            raise ImageUnavailableError(ref)

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            data = load_image(PAGE, loader=loader, vision=True, max_bytes=100)

        # Assert
        self.assertIsNone(data)

    def test_any_other_loader_failure_propagates(self):
        # Arrange
        def loader(ref):
            raise TimeoutError("storage is slow")

        # Act / Assert
        with self.assertRaises(TimeoutError):
            load_image(PAGE, loader=loader, vision=True, max_bytes=100)

    def test_an_oversized_or_unsupported_image_is_not_sent(self):
        # Arrange
        tiff = ImageBlock(ref="files/1/scan.tiff", media_type="image/tiff")

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            too_big = load_image(PAGE, loader=_loader(), vision=True, max_bytes=5)
            unsupported = load_image(tiff, loader=_loader(), vision=True, max_bytes=100)

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
            data = load_image(png, loader=_loader(JPEG), vision=True, max_bytes=100)

        # Assert
        self.assertIsNone(data)

    def test_every_supported_type_is_recognized_by_its_signature(self):
        # Arrange
        samples = {
            "image/jpeg": JPEG,
            "image/png": b"\x89PNG\r\n\x1a\n....",
            "image/gif": b"GIF89a....",
            "image/webp": b"RIFF\x00\x00\x00\x00WEBPVP8 ",
        }

        for media_type, sample in samples.items():
            # Act
            data = load_image(
                ImageBlock(ref="x", media_type=media_type),
                loader=_loader(sample),
                vision=True,
                max_bytes=100,
            )

            # Assert
            self.assertEqual(data, sample)
