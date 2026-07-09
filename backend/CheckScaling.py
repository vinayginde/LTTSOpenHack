import json
import os
import sys
from typing import Any, Dict, List, Optional

import fitz


def check_scaling(pdf_folder: str, _reference_filename: Optional[str] = None) -> Dict[str, Any]:
    """Compare PDFs in `pdf_folder` against the first PDF in the folder.

    The function always selects the first `.pdf` (sorted by filename) as the
    reference, ignoring any filename passed in. Width and height are read from
    `page.rect` of the reference's first page.
    """

    pdf_names = [n for n in sorted(os.listdir(pdf_folder)) if n.lower().endswith(".pdf")]
    if not pdf_names:
        raise FileNotFoundError(f"No PDFs found in folder: {pdf_folder}")
    reference_filename = pdf_names[0]
    reference_path = os.path.join(pdf_folder, reference_filename)

    reference_doc = fitz.open(reference_path)
    reference_page = reference_doc[0]
    reference_width = float(reference_page.rect.width)
    reference_height = float(reference_page.rect.height)
    reference_doc.close()

    scaled_in_count = 0
    scaled_out_count = 0
    non_searchable_count = 0
    files: List[Dict[str, Any]] = []

    for file_name in sorted(os.listdir(pdf_folder)):
        full_path = os.path.join(pdf_folder, file_name)
        if not os.path.isfile(full_path) or not file_name.lower().endswith(".pdf") or file_name == reference_filename:
            continue

        doc = fitz.open(full_path)
        page = doc[0]
        width = float(page.rect.width)
        height = float(page.rect.height)
        text = page.get_text("text") or ""
        doc.close()

        ratio = width / height if height else 0
        reference_ratio = reference_width / reference_height if reference_height else 0

        if len(text) < 50:
            non_searchable_count += 1

        if width < reference_width and height < reference_height:
            scaled_in_count += 1
            status = "scaled_in"
        elif width > reference_width and height > reference_height:
            scaled_out_count += 1
            status = "scaled_out"
        else:
            status = "same"

        files.append(
            {
                "filename": file_name,
                "width": width,
                "height": height,
                "ratio": ratio,
                "reference_ratio": reference_ratio,
                "status": status,
            }
        )

    return {
        "scaled_in_count": scaled_in_count,
        "scaled_out_count": scaled_out_count,
        "non_searchable_count": non_searchable_count,
        "files": files,
        "reference": reference_filename,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python CheckScaling.py <pdf_folder>")

    pdf_folder = sys.argv[1]
    # Ignore any provided filename; the function always uses the first PDF
    result = check_scaling(pdf_folder)
    print(json.dumps(result))
