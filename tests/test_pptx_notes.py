"""Speaker notes read from the .pptx file (no PowerPoint needed)."""

import zipfile

import pytest

from src.presentation.pptx_notes import read_pptx_notes

P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ' \
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
SLIDE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
NOTES_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"


def _notes_xml(paragraphs):
    body = "".join(f"<a:p>{p}</a:p>" for p in paragraphs)
    return (f'<p:notes {P}><p:cSld><p:spTree>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image"/><p:cNvSpPr/>'
            f'<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr></p:sp>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes"/><p:cNvSpPr/>'
            f'<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
            f'<p:txBody>{body}</p:txBody></p:sp>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="4" name="Slide Number"/><p:cNvSpPr/>'
            f'<p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>'
            f'<p:txBody><a:p><a:r><a:t>7</a:t></a:r></a:p></p:txBody></p:sp>'
            f'</p:spTree></p:cSld></p:notes>')


def run(text):
    return f"<a:r><a:t>{text}</a:t></a:r>"


def make_pptx(path, slides):
    """slides: list of (file number, hidden, notes paragraphs or None), in show order."""
    with zipfile.ZipFile(path, "w") as package:
        ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(len(slides)))
        package.writestr("ppt/presentation.xml", f"<p:presentation {P}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
        rels = "".join(f'<Relationship Id="rId{i + 1}" Type="{SLIDE_TYPE}" Target="slides/slide{n}.xml"/>'
                       for i, (n, _, _) in enumerate(slides))
        package.writestr("ppt/_rels/presentation.xml.rels", f"<Relationships {RELS}>{rels}</Relationships>")
        for number, hidden, notes in slides:
            show = ' show="0"' if hidden else ""
            package.writestr(f"ppt/slides/slide{number}.xml", f"<p:sld {P}{show}><p:cSld/></p:sld>")
            if notes is not None:
                package.writestr(f"ppt/slides/_rels/slide{number}.xml.rels",
                                 f'<Relationships {RELS}><Relationship Id="rId9" Type="{NOTES_TYPE}" '
                                 f'Target="../notesSlides/notesSlide{number}.xml"/></Relationships>')
                package.writestr(f"ppt/notesSlides/notesSlide{number}.xml", _notes_xml(notes))
    return path


def test_notes_by_show_position(tmp_path):
    path = make_pptx(tmp_path / "talk.pptx", [
        (3, False, [run("Welcome everyone.") + run(" Today: gestures.")]),   # file slide3 is shown first
        (1, True, [run("Hidden slide notes.")]),                             # hidden: skipped
        (2, False, None),                                                    # no notes
        (4, False, [run("First line") + "<a:br/>" + run("second line"), run("New paragraph.")]),
    ])
    assert read_pptx_notes(path) == {
        1: "Welcome everyone. Today: gestures.",
        3: "First line\nsecond line\nNew paragraph.",
    }


def test_empty_notes_are_left_out(tmp_path):
    path = make_pptx(tmp_path / "talk.pptx", [(1, False, ["", run("  ")])])
    assert read_pptx_notes(path) == {}


def test_not_a_pptx(tmp_path):
    path = tmp_path / "broken.pptx"
    path.write_bytes(b"PK\x03\x04 broken")
    with pytest.raises(zipfile.BadZipFile):
        read_pptx_notes(path)


def test_powerpoint_busy_is_recognised():
    pywintypes = pytest.importorskip("pywintypes")
    from src.presentation.powerpoint_controller import _is_busy

    assert _is_busy(pywintypes.com_error(-2147418111, "Call was rejected by callee.", None, None))
    assert not _is_busy(pywintypes.com_error(-2147188160, "View (unknown member)", None, None))


def test_powerpoint_controller_reads_notes_from_the_file(tmp_path):
    pytest.importorskip("win32com")
    from src.presentation.powerpoint_controller import PowerPointController

    controller = PowerPointController()
    controller.file_path = make_pptx(tmp_path / "talk.pptx", [(1, False, [run("Hello.")])])
    assert controller.slide_notes() == {1: "Hello."}   # no PowerPoint (COM) involved
