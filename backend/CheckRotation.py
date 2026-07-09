import json
import os
import sys
from typing import List, Dict, Any, Optional

import fitz
import pandas as pd


def check_rotated(pdf_folder: str, _excel_path: Optional[str] = None, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Scan PDFs in `pdf_folder` and return rotation info for each file.

    - Does not require an Excel mapping (ignored).
    - Uses `fitz.Page.get_rotation()` when available.
    """

    arr: List[Dict[str, Any]] = []
    multi_page_count = 0

    for file_name in sorted(os.listdir(pdf_folder)):
        if not file_name.lower().endswith(".pdf"):
            continue

        full_path = os.path.join(pdf_folder, file_name)
        if not os.path.isfile(full_path):
            continue

        try:
            with fitz.open(full_path) as doc:
                page_count = len(doc)
                if page_count > 1:
                    multi_page_count += 1

                page = doc[0]
                try:
                    rotation = int(page.get_rotation() or 0)
                except Exception:
                    rotation = int(getattr(page, "rotation", 0) or 0)
        except Exception:
            # Skip files we can't open
            continue

        if rotation:
            arr.append({"filename": file_name, "rotated": rotation, "page_count": page_count})

    result = {
        "count": len(arr),
        "multi_page_count": multi_page_count,
        "files": arr,
        "outputPath": output_path or "",
    }

    if output_path:
        try:
            df = pd.DataFrame(arr)
            df.to_excel(output_path, index=False, sheet_name="sheet1")
        except Exception:
            pass

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python CheckRotation.py <pdf_folder> [excel_path] [output_path]")

    pdf_folder = sys.argv[1]
    excel_path = sys.argv[2] if len(sys.argv) > 2 else None
    output_path = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps(check_rotated(pdf_folder, excel_path, output_path)))
