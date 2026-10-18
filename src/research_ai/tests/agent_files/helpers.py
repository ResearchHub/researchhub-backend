"""Builders for chat file rows and the formats uploads accept."""

import hashlib
import io
import uuid
import zipfile

import fitz
from botocore.exceptions import ClientError
from PIL import Image

from research_ai.models import AgentFile
from research_ai.services.agent_files.extraction import PageImage, UnreadableFileError

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006"
SCAN = object()


def pdf_bytes(*pages: str, **save_options) -> bytes:
    """A PDF with one page per argument; an empty string is a blank page."""
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes(**save_options)
    document.close()
    return data


def stamped_scan(stamp: str) -> tuple:
    """A ``pdf_with_scans`` page: a scan with ``stamp`` as its only text."""
    return SCAN, stamp


def pdf_with_scans(*pages) -> bytes:
    """A PDF whose ``SCAN`` pages hold only an image; other pages hold text."""
    document = fitz.open()
    for content in pages:
        page = document.new_page()
        content, stamp = content if isinstance(content, tuple) else (content, "")
        if content is SCAN:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
            pixmap.clear_with(180)
            page.insert_image(page.rect, pixmap=pixmap)
            content = stamp
        if content:
            page.insert_text((72, 72), content)
    data = document.tobytes()
    document.close()
    return data


def image_bytes(
    size=(40, 30), color="navy", *, mode="RGB", image_format="PNG", **save_options
) -> bytes:
    """An image of one colour, as an upload holds it."""
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, image_format, **save_options)
    return buffer.getvalue()


def docx_bytes(
    body_xml: str,
    *,
    doctype: str = "",
    parts: dict[str, str | bytes] | None = None,
) -> bytes:
    """A minimal .docx whose body is ``body_xml``; ``parts`` adds archive members."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>{doctype}'
        f'<w:document xmlns:w="{W_NS}">'
        f"<w:body>{body_xml}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        for name, content in (parts or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def picture(relationship_id: str, *, linked: bool = False) -> str:
    """A run showing the image ``picture_parts`` gives that relationship id."""
    return (
        "<w:r><w:drawing>"
        f"<wp:inline xmlns:wp='{DRAWING_NS}/wordprocessingDrawing'>"
        f"<a:graphic xmlns:a='{DRAWING_NS}/main'><a:graphicData>"
        f"<pic:pic xmlns:pic='{DRAWING_NS}/picture'><pic:blipFill>"
        f"<a:blip xmlns:r='{RELATIONSHIPS_NS}' "
        f"r:{'link' if linked else 'embed'}='{relationship_id}'/>"
        "</pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline>"
        "</w:drawing></w:r>"
    )


def picture_parts(
    images: dict[str, bytes], *, links: dict[str, str] | None = None
) -> dict[str, str | bytes]:
    """``docx_bytes`` parts for images by relationship id.

    ``links`` maps an id to the address of an image kept outside the file.
    """
    relationships = [
        f"<Relationship Id='{relationship_id}' Type='{RELATIONSHIPS_NS}/image' "
        f"Target='media/{relationship_id}'/>"
        for relationship_id in images
    ] + [
        f"<Relationship Id='{relationship_id}' Type='{RELATIONSHIPS_NS}/image' "
        f"Target='{address}' TargetMode='External'/>"
        for relationship_id, address in (links or {}).items()
    ]
    return {
        "word/_rels/document.xml.rels": (
            f"<Relationships xmlns='{PACKAGE_NS}/relationships'>"
            f"{''.join(relationships)}</Relationships>"
        ),
        **{f"word/media/{name}": data for name, data in images.items()},
    }


def make_file(
    user,
    *,
    message=None,
    status=AgentFile.Status.READY,
    filename="grant.pdf",
    content_type="application/pdf",
    text="[Page 1]\nSpecific aims",
    **fields,
) -> AgentFile:
    """A file row as the upload lifecycle leaves it; sent when ``message``."""
    return AgentFile.objects.create(
        user=user,
        conversation=message.conversation if message is not None else None,
        message=message,
        filename=filename,
        content_type=content_type,
        size_bytes=fields.pop("size_bytes", 100),
        storage_key=f"uploads/research_ai/users/{user.id}/{uuid.uuid4()}/{filename}",
        status=status,
        text=text,
        **fields,
    )


class FakeBucket:
    """Backs a mocked S3 client with a dict of objects.

    ``listable=False`` answers as S3 does to a role without ``s3:ListBucket``:
    403 for an object that is not there.
    """

    def __init__(self, client, *, listable: bool = True):
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.listable = listable
        client.head_object.side_effect = self._head
        client.get_object.side_effect = self._get
        client.put_object.side_effect = self._put
        client.delete_object.side_effect = self._delete
        client.delete_objects.side_effect = self._delete_many

    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store an object; returns its ETag."""
        self.objects[key] = data
        self.content_types[key] = content_type
        return self._etag(key)

    def _etag(self, key: str) -> str:
        return f'"{hashlib.sha256(self.objects[key]).hexdigest()[:32]}"'

    def _missing(self, operation: str, code: str) -> ClientError:
        if not self.listable:
            code = "403" if operation == "HeadObject" else "AccessDenied"
        return ClientError({"Error": {"Code": code}}, operation)

    def _head(self, **request):
        key = request["Key"]
        if key not in self.objects:
            raise self._missing("HeadObject", "404")
        return {
            "ContentLength": len(self.objects[key]),
            "ContentType": self.content_types[key],
            "ETag": self._etag(key),
        }

    def _get(self, **request):
        key = request["Key"]
        if key not in self.objects:
            raise self._missing("GetObject", "NoSuchKey")
        if request.get("IfMatch", self._etag(key)) != self._etag(key):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[key])}

    def _put(self, **request):
        self.put(request["Key"], request["Body"], request["ContentType"])
        return {}

    def _delete(self, **request):
        self.objects.pop(request["Key"], None)
        return {}

    def _delete_many(self, **request):
        for entry in request["Delete"]["Objects"]:
            self.objects.pop(entry["Key"], None)
        return {}


class FakeRender:
    """Stands in for ``render_pdf_page``; ``failing`` pages cannot be rendered."""

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.pages = []

    def __call__(self, data, page, **options):
        self.pages.append(page)
        if page in self.failing:
            raise UnreadableFileError("This PDF page could not be rendered.")
        return PageImage(page, b"jpeg-%d" % page, "image/jpeg", 10, 10)
