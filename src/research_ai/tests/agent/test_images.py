"""Unit tests for resolving image references into request bytes."""

from unittest import TestCase

from research_ai.services.agent.images import (
    MANY_IMAGES,
    MANY_IMAGES_SIDE_PX,
    MAX_IMAGE_SIDE_PX,
    ImageUnavailableError,
    image_placeholder,
    load_image,
    max_image_side_px,
)
from research_ai.services.agent.types import ImageBlock, Message, ToolResultBlock
from research_ai.tests.agent.image_test_helpers import JPEG, WIDE_PNG, image_bytes

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

    def test_an_image_over_the_side_limit_it_is_given_is_not_sent(self):
        # Arrange
        png = ImageBlock(ref="files/1/wide.png", media_type="image/png")

        # Act
        with self.assertLogs(LOGGER, "WARNING"):
            sent = load_image(
                png,
                loader=_loader(WIDE_PNG),
                vision=True,
                max_bytes=MAX_BYTES,
                max_side_px=MANY_IMAGES_SIDE_PX,
            )

        # Assert
        self.assertIsNone(sent)

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


class MaxImageSidePxTests(TestCase):
    def _messages(self, in_tool_result):
        return [
            Message(role="user", content=[PAGE] * (MANY_IMAGES - 8)),
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="t1", content={}, images=(PAGE,) * in_tool_result
                    )
                ],
            ),
        ]

    def test_a_request_with_twenty_images_keeps_the_full_limit(self):
        # Act
        limit = max_image_side_px(self._messages(in_tool_result=8))

        # Assert
        self.assertEqual(limit, MAX_IMAGE_SIDE_PX)

    def test_images_in_every_message_and_tool_result_count_towards_many(self):
        # Act
        limit = max_image_side_px(self._messages(in_tool_result=9))

        # Assert
        self.assertEqual(limit, MANY_IMAGES_SIDE_PX)
