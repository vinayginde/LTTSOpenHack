import argparse
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

import fitz
import pandas as pd

RESTRICTED_CONTENTS = ['"', '-', '.', '°', '/', '\\', ',', '(', ')']
INSTRUMENT_CANDIDATE_PATTERN = r'^[A-Z]\d+[A-Z]\d+$'


def classify_text(text: str) -> Optional[str]:
    """Classify generic text into Pipe-run or Equipment."""
    cleaned = text.strip()
    if not cleaned:
        return None

    has_dash = "-" in cleaned
    has_quote = '"' in cleaned

    if has_quote and has_dash:
        return "Pipe-run"
    if has_dash and not has_quote:
        return "Equipment"
    return None


def is_valid_instrument_candidate(word: str, pid_no: str) -> bool:
    cleaned = str(word).strip()
    if not cleaned:
        return False
    if any(char in cleaned for char in RESTRICTED_CONTENTS):
        return False
    if re.match(INSTRUMENT_CANDIDATE_PATTERN, cleaned.upper()):
        return False
    if pid_no.upper() in cleaned.upper():
        return False
    if len(cleaned) < 3:
        return True
    first_ord = ord(min(cleaned.upper()))
    last_ord = ord(max(cleaned.upper()))
    return 48 <= first_ord <= 57 and 65 <= last_ord <= ord('Z')


def normalize_instrument_text(raw_text: str) -> Optional[str]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) != 2:
        return None
    if not all(re.fullmatch(r"[A-Z0-9]+", line) for line in lines):
        return None
    joined = "".join(lines)
    if any(char in joined for char in RESTRICTED_CONTENTS):
        return None
    if "NOTE" in joined.upper():
        return None
    return joined


def load_copilot_rows(excel_path: str) -> List[Dict[str, object]]:
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Copilot Excel not found: {excel_path}")

    try:
        df = pd.read_excel(excel_path, engine="openpyxl")
    except Exception as exc:
        raise ValueError(f"Unable to read Copilot Excel: {exc}")

    pid_cols = [
        col
        for col in df.columns
        if col.strip().lower()
        in {
            "p&id no.",
            "p&id drg no.",
            "p&id drg no",
            "pid",
            "p&id drg no.",
            "p&id drg no",
            "p&id drg no.",
            "p&id drg no",
        }
    ]
    text_cols = [
        col
        for col in df.columns
        if col.strip().lower() in {"text", "tag id", "tag", "txt"}
    ]
    type_cols = [
        col
        for col in df.columns
        if col.strip().lower() in {"tag type", "tag_type", "tag"}
    ]
    page_cols = [
        col
        for col in df.columns
        if col.strip().lower() in {"page no.", "page no", "page", "pageno", "page_no"}
    ]
    coord_cols = {
        "x1": next((col for col in df.columns if col.strip().lower() == "x1"), None),
        "y1": next((col for col in df.columns if col.strip().lower() == "y1"), None),
        "x2": next((col for col in df.columns if col.strip().lower() == "x2"), None),
        "y2": next((col for col in df.columns if col.strip().lower() == "y2"), None),
    }

    if not pid_cols or not text_cols or not coord_cols["x1"] or not coord_cols["y1"] or not coord_cols["x2"] or not coord_cols["y2"]:
        raise ValueError("Copilot Excel is missing required columns.")

    rows: List[Dict[str, object]] = []
    for _, row in df.iterrows():
        pid_no = str(row[pid_cols[0]]).strip()
        text_val = str(row[text_cols[0]]).strip()
        tag_type = str(row[type_cols[0]]).strip() if type_cols else "Instrument"
        if not pid_no or not text_val:
            continue

        try:
            x1 = float(row[coord_cols["x1"]])
            y1 = float(row[coord_cols["y1"]])
            x2 = float(row[coord_cols["x2"]])
            y2 = float(row[coord_cols["y2"]])
        except Exception:
            continue

        page_no = int(row[page_cols[0]]) if page_cols and not pd.isna(row[page_cols[0]]) else 1
        rows.append(
            {
                "P&ID no.": pid_no,
                "Text": text_val,
                "Tag Type": tag_type,
                "Box ID": 0,
                "X1": x1,
                "Y1": y1,
                "X2": x2,
                "Y2": y2,
                "Page No.": page_no,
            }
        )

    return rows


def extract_instrument_objects_from_pdf(pdf_path: str, pid_no: str, starting_id: int = 1) -> List[Dict[str, object]]:
    """Use the Copilot-style instrument capture algorithm to extract two-line instrument tags."""
    rows: List[Dict[str, object]] = []
    next_box_id = starting_id
    drawn_rects: List[Tuple[float, float, float, float, str]] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        print(f"Warning: Failed to open PDF '{pdf_path}': {exc}", file=sys.stderr)
        return rows

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_no = page_index + 1
        words = page.get_text("words")
        words.sort(key=lambda item: (item[1], item[0]))

        for x1, y1, x2, y2, word, block_no, line_no, word_no in words:
            if not is_valid_instrument_candidate(word, pid_no):
                continue

            rect = fitz.Rect(x1 - 10, y1 - 10, x2 + 10, y2 + 10)
            raw_text = page.get_text("text", clip=rect)
            normalized = normalize_instrument_text(raw_text)
            if not normalized:
                continue

            overlap_index = None
            for index, (ex1, ey1, ex2, ey2, existing_text) in enumerate(drawn_rects):
                existing_rect = fitz.Rect(ex1, ey1, ex2, ey2)
                if rect.intersects(existing_rect):
                    overlap_index = index
                    break

            if overlap_index is not None:
                _, _, _, _, existing_text = drawn_rects[overlap_index]
                if len(normalized) <= len(existing_text):
                    continue
                rows.pop(overlap_index)
                drawn_rects.pop(overlap_index)

            rows.append(
                {
                    "P&ID no.": pid_no,
                    "Text": normalized,
                    "Tag Type": "Instrument",
                    "Box ID": next_box_id,
                    "X1": rect.x0,
                    "Y1": rect.y0,
                    "X2": rect.x1,
                    "Y2": rect.y1,
                    "Page No.": page_no,
                }
            )
            drawn_rects.append((rect.x0, rect.y0, rect.x1, rect.y1, normalized))
            next_box_id += 1

    doc.close()
    return rows


def extract_text_objects_from_pdf(pdf_path: str, pid_no: str, starting_id: int = 1) -> List[Dict[str, object]]:
    """Extract text objects and bounding boxes from a PDF using PyMuPDF."""
    rows: List[Dict[str, object]] = []
    box_id = starting_id

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        print(f"Warning: Failed to open PDF '{pdf_path}': {exc}", file=sys.stderr)
        return rows

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_no = page_index + 1
        words = page.get_text("words")
        words.sort(key=lambda item: (item[1], item[0]))

        for x1, y1, x2, y2, word, block_no, line_no, word_no in words:
            text = str(word).strip()
            if not text:
                continue

            tag_type = classify_text(text)
            if not tag_type:
                continue

            rows.append(
                {
                    "P&ID no.": pid_no,
                    "Text": text,
                    "Box ID": box_id,
                    "Tag Type": tag_type,
                    "X1": x1,
                    "Y1": y1,
                    "X2": x2,
                    "Y2": y2,
                    "Page No.": page_no,
                    
                }
            )
            box_id += 1

    doc.close()
    return rows


def row_key(row: Dict[str, object]) -> Tuple[object, ...]:
    return (
        row.get("P&ID no."),
        row.get("Text"),
        row.get("Tag Type"),
        row.get("X1"),
        row.get("Y1"),
        row.get("X2"),
        row.get("Y2"),
        row.get("Page No."),
    )


def dedupe_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen: Set[Tuple[object, ...]] = set()
    unique: List[Dict[str, object]] = []

    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    return unique


def process_folder(input_folder: str, output_file: str, copilot_excel: Optional[str] = None) -> None:
    """Process all PDFs in the input folder and export results to Excel."""
    if not os.path.isdir(input_folder):
        raise FileNotFoundError(f"Input folder not found: {input_folder}")

    pdf_files = [
        f for f in sorted(os.listdir(input_folder)) if f.lower().endswith(".pdf")
    ]
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in folder: {input_folder}")

    output_rows: List[Dict[str, object]] = []

    copilot_rows: List[Dict[str, object]] = []
    if copilot_excel:
        try:
            copilot_rows = load_copilot_rows(copilot_excel)
        except Exception as exc:
            print(f"Warning: failed to read Copilot Excel '{copilot_excel}': {exc}", file=sys.stderr)
            copilot_rows = []

    for i, pdf_name in enumerate(pdf_files, start=1):
        pdf_path = os.path.join(input_folder, pdf_name)
        pid_no = os.path.splitext(pdf_name)[0]

        generic_rows = extract_text_objects_from_pdf(pdf_path, pid_no, starting_id=1)
        output_rows.extend(generic_rows)

        if not copilot_rows:
            instrument_rows = extract_instrument_objects_from_pdf(pdf_path, pid_no, starting_id=1)
            output_rows.extend(instrument_rows)

        print(f"PROGRESS:{pdf_name}:{i}:{len(pdf_files)}", flush=True)

    output_rows.extend(copilot_rows)
    output_rows = dedupe_rows(output_rows)

    for index, row in enumerate(output_rows, start=1):
        row["Box ID"] = index

    df = pd.DataFrame(output_rows, columns=[
        "P&ID no.",
        "Text",
        "Tag Type",
        "Box ID",
        "X1",
        "Y1",
        "X2",
        "Y2",
        "Page No.",
    ])

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="capture_coordinates")

    print(f"Exported {len(output_rows)} rows to {output_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text objects from PDFs and export to Excel."
    )
    parser.add_argument(
        "input_folder",
        help="Path to the folder containing PDF files.",
    )
    parser.add_argument(
        "output_file",
        nargs="?",
        default="capture_coordinates.xlsx",
        help="Excel output file path (default: capture_coordinates.xlsx).",
    )
    parser.add_argument(
        "copilot_excel",
        nargs="?",
        default=None,
        help="Optional Copilot-generated Excel file to merge instrument rows from.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        process_folder(args.input_folder, args.output_file, copilot_excel=args.copilot_excel)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
