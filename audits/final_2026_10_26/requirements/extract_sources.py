"""Read local user-provided requirements; never modify the original documents."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from pypdf import PdfReader

OUT = Path(__file__).resolve().parent
WORKSPACE = OUT.parents[3]
names = [
    "Assignment 1 - Distributed Streaming-based Client-Server Collaboration Application(1).pdf",
    "Assignment1_Network_Application_Guide.pptx", "network_assignment_demo.zip",
]
manifest = [{"file": name, "sha256": hashlib.sha256((WORKSPACE / name).read_bytes()).hexdigest(),
             "bytes": (WORKSPACE / name).stat().st_size} for name in names]
(OUT / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
reader = PdfReader(WORKSPACE / names[0])
(OUT / "assignment_pdf.txt").write_text("\n\n".join(
    f"===== PDF PAGE {i} =====\n{page.extract_text()}" for i, page in enumerate(reader.pages, 1)), encoding="utf-8")
with zipfile.ZipFile(WORKSPACE / names[1]) as deck:
    slides = sorted((name for name in deck.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                    key=lambda name: int(re.search(r"slide(\d+)\.xml", name).group(1)))
    text = []
    for i, name in enumerate(slides, 1):
        root = ET.fromstring(deck.read(name))
        paragraphs = [node.text or "" for node in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")]
        text.append(f"===== SLIDE {i} =====\n" + "\n".join(paragraphs))
    (OUT / "guide_slides.txt").write_text("\n\n".join(text), encoding="utf-8")
with zipfile.ZipFile(WORKSPACE / names[2]) as archive:
    (OUT / "demo_inventory.json").write_text(json.dumps(archive.namelist(), indent=2), encoding="utf-8")
