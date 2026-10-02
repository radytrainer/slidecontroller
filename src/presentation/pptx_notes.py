"""
Speaker notes read straight from the .pptx file (no PowerPoint needed).

A .pptx is a ZIP of XML parts::

    ppt/presentation.xml            slide order   <p:sldId r:id="rId2"/> ...
    ppt/_rels/presentation.xml.rels rId2 -> slides/slide1.xml
    ppt/slides/slide1.xml           <p:sld show="0"> = hidden slide
    ppt/slides/_rels/slide1.xml.rels  -> ../notesSlides/notesSlide1.xml
    ppt/notesSlides/notesSlide1.xml the notes text box (<p:ph type="body"/>)

Reading the file is instant and always works, while asking PowerPoint over
COM right after the slide show starts is often rejected ("Call was rejected by
callee") because PowerPoint is still busy.

Slide numbers are slide show positions, like PowerPoint's
CurrentShowPosition: hidden slides are skipped.
"""

import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
NOTES_SLIDE = "/notesSlide"
HIDDEN = {"0", "false"}


def read_pptx_notes(file_path: str | Path) -> dict[int, str]:
    """{slide show position: notes text} for every visible slide with notes."""
    notes: dict[int, str] = {}
    with zipfile.ZipFile(file_path) as package:
        names = set(package.namelist())

        def xml(name: str):
            return ElementTree.fromstring(package.read(name))

        def relationships(part: str) -> dict[str, tuple[str, str]]:
            """{rId: (type, part name)} of a part."""
            folder, file = posixpath.split(part)
            rels_name = posixpath.join(folder, "_rels", file + ".rels")
            if rels_name not in names:
                return {}
            result = {}
            for rel in xml(rels_name).findall("rel:Relationship", NS):
                if rel.get("TargetMode") == "External":
                    continue
                target = posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
                result[rel.get("Id")] = (rel.get("Type", ""), target)
            return result

        presentation = "ppt/presentation.xml"
        slide_parts = relationships(presentation)
        position = 0
        for slide_id in xml(presentation).findall("p:sldIdLst/p:sldId", NS):
            _, slide_part = slide_parts.get(slide_id.get(f"{{{NS['r']}}}id"), ("", ""))
            if slide_part not in names:
                continue
            if xml(slide_part).get("show", "1").lower() in HIDDEN:
                continue
            position += 1
            notes_part = next((target for kind, target in relationships(slide_part).values()
                               if kind.endswith(NOTES_SLIDE)), None)
            if notes_part in names:
                text = _notes_text(xml(notes_part))
                if text:
                    notes[position] = text
    return notes


def _notes_text(notes_slide) -> str:
    for shape in notes_slide.iter(f"{{{NS['p']}}}sp"):
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if placeholder is None or placeholder.get("type") != "body":
            continue
        paragraphs = []
        for paragraph in shape.findall("p:txBody/a:p", NS):
            parts = []
            for node in paragraph:
                tag = node.tag.rsplit("}", 1)[-1]
                if tag in ("r", "fld"):
                    parts.append("".join(t.text or "" for t in node.findall("a:t", NS)))
                elif tag == "br":
                    parts.append("\n")
            paragraphs.append("".join(parts))
        return "\n".join(paragraphs).strip()
    return ""
