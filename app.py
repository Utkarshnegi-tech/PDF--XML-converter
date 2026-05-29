from flask import Flask, request, jsonify, send_from_directory
import fitz  # PyMuPDF
import os
import re
import statistics
from datetime import datetime, timezone
from lxml import etree

app = Flask(__name__, static_folder="static")
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

NS = "http://docbook.org/ns/docbook"
XLINK = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_id_counter = 0
LIST_BULLET_RE = re.compile(r"^[\u2022\u2023\u25E6\u2043\u2219•●○◦▪▫\-\*]\s+")
LIST_NUMBER_RE = re.compile(r"^(\d+|[ivxlcdm]+|[IVXLCDM]+)[\.\)]\s+", re.I)
URL_RE = re.compile(r"https?://[^\s<>\]]+", re.I)

# XML 1.0: allow tab, LF, CR, and valid Unicode scalars; strip NULLs and controls.
_INVALID_XML_CHAR_RE = re.compile(
    "["
    "\x00-\x08"
    "\x0B\x0C"
    "\x0E-\x1F"
    "\x7F-\x84"
    "\x85-\x9F"
    "\uFDD0-\uFDEF"
    "\uFFFE\uFFFF"
    "]"
)

def sanitize_xml_text(value):
    """Make text safe for XML elements and attributes (Unicode, no NULL/control chars)."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if "\x00" in value:
        value = value.replace("\x00", "")
    return _INVALID_XML_CHAR_RE.sub("", value)

def sanitize_xml_tree(root):
    """Sanitize all text, tails, and attribute values in an element tree."""
    for elem in root.iter():
        if elem.text:
            elem.text = sanitize_xml_text(elem.text)
        if elem.tail:
            elem.tail = sanitize_xml_text(elem.tail)
        for key, val in list(elem.attrib.items()):
            if isinstance(val, str):
                elem.attrib[key] = sanitize_xml_text(val)

def new_id(prefix="d"):
    global _id_counter
    _id_counter += 1
    return f"{prefix}-{_id_counter:07d}"

def reset_ids():
    global _id_counter
    _id_counter = 0

def el(tag, parent=None, attrib=None, text=None):
    attrib = {
        k: sanitize_xml_text(v) if isinstance(v, str) else v
        for k, v in (attrib or {}).items()
    }
    attrib[f"{{{XML_NS}}}id"] = new_id()
    if parent is not None:
        node = etree.SubElement(parent, f"{{{NS}}}{tag}", attrib)
    else:
        node = etree.Element(f"{{{NS}}}{tag}", attrib)
    if text is not None:
        node.text = sanitize_xml_text(text)
    return node

def span_style(span):
    flags = span.get("flags", 0)
    font = span.get("font", "")
    return {
        "bold": bool(flags & 2**4) or "Bold" in font or "bold" in font,
        "italic": bool(flags & 2**1)
        or "Italic" in font
        or "italic" in font
        or "Oblique" in font,
    }


COVERAGE_TARGET = 0.92

# Prefer dehyphenated, sorted text from PyMuPDF when available.
try:
    _TEXT_FLAGS = (
        fitz.TEXT_DEHYPHENATE
        | fitz.TEXT_PRESERVE_LIGATURES
        | fitz.TEXT_MEDIABOX_CLIP
    )
except AttributeError:
    _TEXT_FLAGS = 0

def normalize_for_coverage(text):
    if not text:
        return ""
    text = sanitize_xml_text(text)
    return re.sub(r"\s+", "", text)

def get_page_reference_text(page):
    try:
        return page.get_text("text", sort=True, flags=_TEXT_FLAGS)
    except TypeError:
        try:
            return page.get_text("text", sort=True)
        except TypeError:
            return page.get_text("text")

def _span_from_text(text, bbox, page_index, size=12.0, bold=False, italic=False, font=""):
    return {
        "text": sanitize_xml_text(text),
        "size": round(size, 2),
        "bold": bold,
        "italic": italic,
        "font": font,
        "bbox": bbox,
        "x0": bbox[0],
        "y0": bbox[1],
        "x1": bbox[2],
        "y1": bbox[3],
        "page": page_index,
    }

def _span_text_from_dict_span(span):
    text = span.get("text") or ""
    if text:
        return text
    chars = span.get("chars")
    if chars:
        return "".join(c.get("c", "") for c in chars)
    return ""

def extract_spans_from_dict(page, page_index):
    raw = []
    try:
        page_dict = page.get_text("dict", sort=True)
    except TypeError:
        page_dict = page.get_text("dict")

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = sorted(
            block.get("lines", []),
            key=lambda ln: (round(ln["bbox"][1], 1), ln["bbox"][0]),
        )
        for line in lines:
            line_spans = sorted(line.get("spans", []), key=lambda sp: sp["bbox"][0])
            for span in line_spans:
                text = _span_text_from_dict_span(span)
                if not text:
                    continue
                style = span_style(span)
                bbox = span["bbox"]
                raw.append(_span_from_text(
                    text,
                    bbox,
                    page_index,
                    size=span.get("size", 12.0),
                    bold=style["bold"],
                    italic=style["italic"],
                    font=span.get("font", ""),
                ))
    return raw

def extract_spans_from_rawdict(page, page_index):
    raw = []
    try:
        page_dict = page.get_text("rawdict", sort=True)
    except (TypeError, ValueError):
        return extract_spans_from_dict(page, page_index)

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = sorted(
            block.get("lines", []),
            key=lambda ln: (round(ln["bbox"][1], 1), ln["bbox"][0]),
        )
        for line in lines:
            line_spans = sorted(line.get("spans", []), key=lambda sp: sp["bbox"][0])
            for span in line_spans:
                text = _span_text_from_dict_span(span)
                if not text:
                    continue
                style = span_style(span)
                bbox = span["bbox"]
                raw.append(_span_from_text(
                    text,
                    bbox,
                    page_index,
                    size=span.get("size", 12.0),
                    bold=style["bold"],
                    italic=style["italic"],
                    font=span.get("font", ""),
                ))
    return raw

def extract_spans_from_words(page, page_index):
    try:
        words = page.get_text("words", sort=True)
    except TypeError:
        words = page.get_text("words")
    if not words:
        return []

    raw = []
    for w in words:
        if len(w) < 4:
            continue
        x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]
        if word is None:
            continue
        word = str(word)
        if not word.strip():
            continue
        height = max(y1 - y0, 8.0)
        raw.append(_span_from_text(
            word + " ",
            (x0, y0, x1, y1),
            page_index,
            size=height * 0.85,
        ))
    return raw

def extract_spans_from_blocks(page, page_index):
    try:
        blocks = page.get_text("blocks", sort=True)
    except TypeError:
        blocks = page.get_text("blocks")

    raw = []
    for block in blocks:
        if len(block) < 7 or block[6] != 0:
            continue
        text = (block[4] or "").strip()
        if not text:
            continue
        x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
        height = max(y1 - y0, 10.0)
        raw.append(_span_from_text(
            text if text.endswith("\n") else text + "\n",
            (x0, y0, x1, y1),
            page_index,
            size=height * 0.75,
        ))
    return raw

def _text_length(spans):
    return sum(len(s.get("text", "")) for s in spans)

def page_paragraph_coverage(paragraphs, reference_text):
    ref = normalize_for_coverage(reference_text)
    if not ref:
        return 1.0
    got = normalize_for_coverage(
        "\n".join(paragraph_text(p) for p in paragraphs)
    )
    return len(got) / len(ref) if ref else 1.0

def plain_text_to_page_paragraphs(page, page_index):
    """Maximum-retention path: mirror PyMuPDF plain text output."""
    text = get_page_reference_text(page)
    if not text.strip():
        return []

    paragraphs = []
    y_base = float(page_index) * 10000

    chunks = re.split(r"\n{2,}", text)
    if len(chunks) <= 1:
        chunks = text.split("\n")

    for i, chunk in enumerate(chunks):
        body = chunk.strip()
        if not body:
            continue
        body = re.sub(r"[ \t]+", " ", body)
        y = y_base + i * 18
        paragraphs.append([
            _span_from_text(body, (0, y, 600, y + 14), page_index, size=12.0),
        ])
    return paragraphs

def supplement_missing_lines(paragraphs, reference_text, page_index):
    """Add reference lines that structured extraction skipped."""
    seen = set()
    for para in paragraphs:
        for line in paragraph_text(para).splitlines():
            norm = normalize_for_coverage(line.strip())
            if norm:
                seen.add(norm)

    ref_norm = normalize_for_coverage(reference_text)
    if not ref_norm:
        return paragraphs

    y_base = float(page_index) * 10000 + 5000
    added = 0
    for line in reference_text.splitlines():
        line_body = line.strip()
        if not line_body:
            continue
        line_norm = normalize_for_coverage(line_body)
        if line_norm and line_norm not in seen:
            y = y_base + added * 16
            paragraphs.append([
                _span_from_text(line_body, (0, y, 600, y + 14), page_index, size=12.0),
            ])
            seen.add(line_norm)
            added += 1
    return paragraphs

def full_page_fallback_paragraphs(page, page_index, reference_text):
    """Single paragraph with all page text — guarantees maximum character retention."""
    compact = sanitize_xml_text(" ".join(reference_text.split()))
    if not compact:
        return []
    y = float(page_index) * 10000
    return [[_span_from_text(compact, (0, y, 600, y + 20), page_index, size=12.0)]]

def extract_page_paragraphs(page, page_index):
    reference_text = get_page_reference_text(page)
    extractors = (
        extract_spans_from_rawdict,
        extract_spans_from_dict,
        extract_spans_from_blocks,
        extract_spans_from_words,
    )

    best_paragraphs = []
    best_cov = 0.0

    for extractor in extractors:
        spans = extractor(page, page_index)
        if not spans:
            continue
        spans.sort(key=lambda s: (round(s["y0"], 1), s["x0"]))
        paragraphs = group_spans_into_paragraphs(spans)
        cov = page_paragraph_coverage(paragraphs, reference_text)
        if cov > best_cov:
            best_cov = cov
            best_paragraphs = paragraphs

    plain_paragraphs = plain_text_to_page_paragraphs(page, page_index)
    plain_cov = page_paragraph_coverage(plain_paragraphs, reference_text)

    if plain_cov >= best_cov:
        best_paragraphs = plain_paragraphs
        best_cov = plain_cov

    if best_cov < COVERAGE_TARGET:
        best_paragraphs = plain_paragraphs
        best_cov = plain_cov

    if best_cov < COVERAGE_TARGET:
        best_paragraphs = supplement_missing_lines(
            best_paragraphs, reference_text, page_index
        )
        best_cov = page_paragraph_coverage(best_paragraphs, reference_text)

    if best_cov < COVERAGE_TARGET:
        best_paragraphs = full_page_fallback_paragraphs(
            page, page_index, reference_text
        )

    return best_paragraphs

def extract_spans(pdf_path):
    doc = fitz.open(pdf_path)
    pages = []
    for page_index, page in enumerate(doc):
        pages.append(extract_page_paragraphs(page, page_index))
    doc.close()
    return pages

def group_spans_into_lines(spans):
    if not spans:
        return []

    lines = []
    current_line = [spans[0]]
    line_y = statistics.median([spans[0]["y0"], spans[0]["y1"]])

    for span in spans[1:]:
        span_y = statistics.median([span["y0"], span["y1"]])
        line_height = max(s["y1"] - s["y0"] for s in current_line)
        tolerance = max(4.0, line_height * 0.55, span["size"] * 0.45)
        if abs(span_y - line_y) <= tolerance:
            current_line.append(span)
        else:
            current_line.sort(key=lambda s: s["x0"])
            lines.append(current_line)
            current_line = [span]
            line_y = span_y
    current_line.sort(key=lambda s: s["x0"])
    lines.append(current_line)
    return lines

def group_spans_into_paragraphs(spans):
    if not spans:
        return []

    lines = group_spans_into_lines(spans)
    paragraphs = []
    current_para = []
    prev_bottom = None

    for line in lines:
        line_top = min(s["y0"] for s in line)
        line_bottom = max(s["y1"] for s in line)
        line_size = statistics.median([s["size"] for s in line])

        if prev_bottom is not None:
            gap = line_top - prev_bottom
            # Wider gap threshold keeps logical paragraphs together
            if gap > max(line_size * 1.85, 6.0):
                if current_para:
                    paragraphs.append(current_para)
                current_para = []

        current_para.extend(line)
        prev_bottom = line_bottom

    if current_para:
        paragraphs.append(current_para)

    return merge_hyphenated_paragraphs(paragraphs)

def merge_hyphenated_paragraphs(paragraphs):
    if len(paragraphs) < 2:
        return paragraphs

    merged = [paragraphs[0]]
    for para in paragraphs[1:]:
        prev = merged[-1]
        prev_text = "".join(s["text"] for s in prev).strip()
        if prev_text.endswith("-") and para and para[0]["text"][:1].islower():
            prev[-1]["text"] = prev[-1]["text"].rstrip("-")
            merged[-1].extend(para)
        else:
            merged.append(para)
    return merged

def paragraph_text(spans):
    if not spans:
        return ""
    parts = []
    prev = None
    for span in spans:
        t = span["text"]
        if not t:
            continue
        if prev is not None:
            gap = span["x0"] - prev["x1"]
            prev_t = prev["text"]
            need_space = (
                gap > max(1.5, prev["size"] * 0.15)
                and not prev_t.endswith((" ", "-", "\u00ad"))
                and not t.startswith((" ", ".", ",", ";", ":", "!", "?", ")", "'", '"'))
            )
            if need_space:
                parts.append(" ")
        parts.append(t)
        prev = span
    return "".join(parts).strip()

def paragraph_dominant_size(spans):
    sizes = [s["size"] for s in spans]
    return statistics.median(sizes) if sizes else 12.0

def paragraph_is_bold(spans):
    weights = [1.2 if s["bold"] else 1.0 for s in spans]
    bold_chars = sum(len(s["text"]) * w for s, w in zip(spans, weights))
    total = sum(len(s["text"]) for s in spans) or 1
    return bold_chars / total > 1.05

def base_font_size(pages):
    sizes = []
    for page in pages:
        for para in page:
            text = paragraph_text(para)
            if len(text) < 3:
                continue
            if LIST_BULLET_RE.match(text) or LIST_NUMBER_RE.match(text):
                continue
            sizes.append(paragraph_dominant_size(para))
    if not sizes:
        return 12.0
    return statistics.median(sizes)

def size_thresholds(pages, base):
    sizes = []
    for page in pages:
        for para in page:
            text = paragraph_text(para)
            if len(text) >= 3:
                sizes.append(paragraph_dominant_size(para))
    if not sizes:
        return {"title": base + 4, "section": base + 2, "subsection": base + 1}

    unique = sorted(set(sizes), reverse=True)
    return {
        "title": max(base * 1.45, unique[0] if unique else base + 4),
        "section": max(base * 1.22, base + 1.8),
        "subsection": max(base * 1.1, base + 0.9),
    }

def classify_paragraph(spans, base, thresholds):
    text = paragraph_text(spans)
    if not text:
        return "empty"
    if LIST_BULLET_RE.match(text) or LIST_NUMBER_RE.match(text):
        return "list_item"
    n = len(text)
    # Long blocks are body text — never drop them as headings-only
    if n > 200:
        return "para"
    if n > 120 and not (text.isupper() and n < 80):
        return "para"

    size = paragraph_dominant_size(spans)
    bold = paragraph_is_bold(spans)

    if len(text) < 80 and text.isupper() and bold:
        return "section"

    if size >= thresholds["title"]:
        if n <= 160 or (bold and n <= 200):
            return "title"
        return "para"

    if size >= thresholds["section"]:
        if n <= 100 or (bold and n <= 130):
            return "section"
        return "para"

    if size >= thresholds["subsection"]:
        if n <= 85 or (bold and n <= 110):
            return "subsection"
        return "para"

    if bold and n < 70 and size >= base * 1.06:
        return "subsection"

    return "para"

def strip_list_marker(text):
    text = LIST_BULLET_RE.sub("", text)
    text = LIST_NUMBER_RE.sub("", text)
    return text.strip()

def make_para_with_emphasis(parent, spans, plain_text=None):
    if not spans and not plain_text:
        return None
    para = el("para", parent)

    if plain_text is not None:
        spans = [{"text": plain_text, "bold": False, "italic": False}]

    groups = []
    for s in spans:
        style = ("italic" if s["italic"] else "") + ("bold" if s["bold"] else "")
        if groups and groups[-1][0] == style:
            groups[-1][1].append(s["text"])
        else:
            groups.append([style, [s["text"]]])

    for style, texts in groups:
        text = sanitize_xml_text("".join(texts).strip())
        if not text:
            continue
        if not style:
            if para.text:
                para.text = sanitize_xml_text(para.text + " " + text)
            elif not list(para):
                para.text = text
            else:
                children = list(para)
                tail = ((children[-1].tail or "") + " " + text).strip() + " "
                children[-1].tail = sanitize_xml_text(tail)
        else:
            roles = []
            if "bold" in style:
                roles.append("bold")
            if "italic" in style:
                roles.append("italic")
            em = el("emphasis", para, {"role": sanitize_xml_text(" ".join(roles))})
            em.text = text
            em.tail = " "
    return para

def add_links_to_para(para, text):
    urls = URL_RE.findall(text)
    if not urls:
        return
    for url in urls:
        link = el("link", para, {f"{{{XLINK}}}href": url})
        link.text = url

def build_docbook(pages, metadata=None):
    reset_ids()
    base = base_font_size(pages)
    thresholds = size_thresholds(pages, base)
    metadata = metadata or {}

    nsmap = {None: NS, "xlink": XLINK}
    book = etree.Element(f"{{{NS}}}book", nsmap=nsmap)
    book.set(f"{{{XML_NS}}}id", new_id("b"))
    book.set("version", "5.0")

    info = el("info", book)
    doc_title = metadata.get("title") or "Untitled Document"
    el("title", info, text=doc_title)
    if metadata.get("author"):
        authgroup = el("authorgroup", info)
        author = el("author", authgroup)
        person = el("personname", author)
        el("firstname", person, text=metadata["author"])
    el("pubdate", info, text=datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    stats = {
        "pages": len(pages),
        "chapters": 0,
        "sections": 0,
        "paragraphs": 0,
        "list_items": 0,
    }

    current_chapter = None
    current_section = None
    current_subsection = None
    list_buffer = []
    list_is_ordered = False
    title_assigned = False

    def para_parent():
        if current_subsection is not None:
            return current_subsection
        if current_section is not None:
            return current_section
        if current_chapter is not None:
            return current_chapter
        return book

    def flush_list():
        nonlocal list_buffer, list_is_ordered
        if not list_buffer:
            return
        parent = para_parent()
        tag = "orderedlist" if list_is_ordered else "itemizedlist"
        lst = el(tag, parent)
        for _item_text, item_spans in list_buffer:
            li = el("listitem", lst)
            clean = strip_list_marker(paragraph_text(item_spans))
            if len(item_spans) == 1:
                item_spans[0]["text"] = clean
                make_para_with_emphasis(li, item_spans)
            else:
                make_para_with_emphasis(li, [], plain_text=clean)
        stats["list_items"] += len(list_buffer)
        list_buffer = []

    def flush_para(spans):
        if not spans:
            return
        text = paragraph_text(spans)
        if not text:
            return
        parent = para_parent()
        para = make_para_with_emphasis(parent, spans)
        if para is not None and URL_RE.search(text):
            add_links_to_para(para, text)
        stats["paragraphs"] += 1

    for page in pages:
        for para_spans in page:
            role = classify_paragraph(para_spans, base, thresholds)
            text = paragraph_text(para_spans)

            if role == "empty":
                continue

            if role == "list_item":
                flush_list()
                ordered = bool(LIST_NUMBER_RE.match(text))
                if list_buffer and ordered != list_is_ordered:
                    flush_list()
                list_is_ordered = ordered
                list_buffer.append((text, para_spans))
                continue

            flush_list()

            if role == "title":
                stats["chapters"] += 1
                heading = text if len(text) <= 120 else text[:117] + "..."
                current_chapter = el("chapter", book)
                ch_info = el("info", current_chapter)
                el("title", ch_info, text=heading)
                current_section = None
                current_subsection = None
                if not title_assigned:
                    info_title = info.find(f"{{{NS}}}title")
                    if info_title is not None:
                        info_title.text = heading
                    title_assigned = True
                if len(text) > 120:
                    flush_para(para_spans)

            elif role == "section":
                parent = current_chapter if current_chapter is not None else book
                if current_chapter is None:
                    current_chapter = el("chapter", book)
                    ch_info = el("info", current_chapter)
                    el("title", ch_info, text="Content")
                    parent = current_chapter
                stats["sections"] += 1
                current_section = el("section", parent)
                sec_info = el("info", current_section)
                heading = text if len(text) <= 100 else text[:97] + "..."
                el("title", sec_info, text=heading)
                current_subsection = None
                if len(text) > 100:
                    flush_para(para_spans)

            elif role == "subsection":
                parent = current_section or current_chapter or book
                if current_chapter is None:
                    current_chapter = el("chapter", book)
                    ch_info = el("info", current_chapter)
                    el("title", ch_info, text="Content")
                    parent = current_chapter
                stats["sections"] += 1
                current_subsection = el("section", parent)
                sub_info = el("info", current_subsection)
                heading = text if len(text) <= 90 else text[:87] + "..."
                el("title", sub_info, text=heading)
                if len(text) > 90:
                    flush_para(para_spans)

            else:
                flush_para(para_spans)

    flush_list()
    return book, stats

def extract_metadata(pdf_path):
    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}
    doc.close()
    return {
        "title": sanitize_xml_text((meta.get("title") or "").strip()),
        "author": sanitize_xml_text((meta.get("author") or "").strip()),
    }

def to_xml_string(root):
    sanitize_xml_tree(root)
    return etree.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    ).decode("utf-8")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    save_path = os.path.join(UPLOAD_FOLDER, f.filename)
    f.save(save_path)

    try:
        pages = extract_spans(save_path)
        if not any(pages):
            return jsonify({
                "error": "No extractable text found. Scanned PDFs require OCR.",
            }), 422

        metadata = extract_metadata(save_path)
        book_el, stats = build_docbook(pages, metadata)
        xml_output = to_xml_string(book_el)

        flat_paras = sum(len(p) for p in pages)
        extracted_norm = normalize_for_coverage(
            "\n".join(
                paragraph_text(para)
                for page in pages
                for para in page
            )
        )
        pdf_norm = ""
        with fitz.open(save_path) as doc:
            for page in doc:
                pdf_norm += normalize_for_coverage(get_page_reference_text(page))

        extracted_chars = len(extracted_norm)
        pdf_chars = len(pdf_norm)
        coverage = round(100 * extracted_chars / pdf_chars, 1) if pdf_chars else 100.0

        return jsonify({
            "xml": xml_output,
            "stats": {
                **stats,
                "blocks_detected": flat_paras,
                "base_font_pt": round(base_font_size(pages), 2),
                "chars_extracted": extracted_chars,
                "chars_in_pdf": pdf_chars,
                "coverage_percent": coverage,
            },
            "metadata": metadata,
        })
    except ValueError as e:
        return jsonify({
            "error": "XML generation failed: invalid characters in document text. "
            + str(e),
        }), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
