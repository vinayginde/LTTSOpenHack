import json
import os
import sys
from typing import Any, Dict, List

import fitz


def check_scaling(pdf_folder: str, reference_filename: str) -> Dict[str, Any]:
    reference_path = os.path.join(pdf_folder, reference_filename)
    if not os.path.isfile(reference_path):
        raise FileNotFoundError(f"Reference PDF not found: {reference_path}")

    reference_doc = fitz.open(reference_path)
    reference_page = reference_doc[0]
    reference_width = float(reference_page.rect.width)
    reference_height = float(reference_page.rect.height)
    reference_doc.close()

    scaled_in_count = 0
    scaled_out_count = 0
    files: List[Dict[str, Any]] = []

    for file_name in sorted(os.listdir(pdf_folder)):
        full_path = os.path.join(pdf_folder, file_name)
        if not os.path.isfile(full_path) or file_name == reference_filename:
            continue

        doc = fitz.open(full_path)
        page = doc[0]
        width = float(page.rect.width)
        height = float(page.rect.height)
        doc.close()

        ratio = width / height if height else 0
        reference_ratio = reference_width / reference_height if reference_height else 0

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
        "files": files,
        "reference": reference_filename,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python CheckScaling.py <pdf_folder> <reference_filename>")

    result = check_scaling(sys.argv[1], sys.argv[2])
    print(json.dumps(result))
