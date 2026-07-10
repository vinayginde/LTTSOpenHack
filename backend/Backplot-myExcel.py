import argparse
import os
import sys
from typing import List, Optional

import fitz
import pandas as pd


def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        column = normalized.get(candidate.lower())
        if column is not None:
            return column
    return None


def require_column(df: pd.DataFrame, candidates: List[str], label: str) -> str:
    column = find_column(df, candidates)
    if column is None:
        raise ValueError(f"Excel is missing required column: {label}")
    return column


def safe_float(value: object) -> Optional[float]:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_pid(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def draw_row(page: fitz.Page, row: pd.Series, columns: dict) -> bool:
    x1 = safe_float(row[columns["x1"]])
    y1 = safe_float(row[columns["y1"]])
    x2 = safe_float(row[columns["x2"]])
    y2 = safe_float(row[columns["y2"]])

    if None in (x1, y1, x2, y2):
        return False

    rect = fitz.Rect(x1, y1, x2, y2)
    label_rect = fitz.Rect(x1, y1 - 18, x2, y2)
    tag_type = str(row[columns["tag_type"]]).strip().lower() if columns["tag_type"] else ""
    box_id = row[columns["box_id"]] if columns["box_id"] else ""

    if tag_type == "instrument":
        page.draw_rect(rect, color=(0, 1, 0), width=1, overlay=True)
    elif tag_type in {"pipe run", "pipe-run", "pipe_run"}:
        page.draw_rect(
            rect,
            color=(0.0, 0.2, 0.4),
            width=2,
            fill=(1.0, 1.0, 0.4),
            fill_opacity=0.25,
            overlay=True,
        )
    elif tag_type == "equipment":
        page.draw_rect(
            rect,
            color=(0.1, 0.5, 0.1),
            width=2,
            fill=(0.7, 0.9, 0.7),
            fill_opacity=0.3,
            overlay=True,
        )
    elif tag_type == "emergency shutdown":
        page.draw_rect(
            rect,
            color=(0.8, 0.4, 0.0),
            width=2,
            fill=(1.0, 0.85, 0.6),
            fill_opacity=0.3,
            overlay=True,
        )
    else:
        page.draw_rect(
            rect,
            color=(0.2, 0.4, 0.0),
            width=2,
            fill=(1.0, 0.85, 0.2),
            fill_opacity=0.3,
            overlay=True,
        )

    if str(box_id).strip():
        page.insert_textbox(
            label_rect,
            f"B-{box_id}\n",
            fontsize=8,
            color=(0, 0, 1),
            overlay=True,
            align=1,
        )

    return True


def process_backplot(input_folder: str, excel_path: str, output_folder: str) -> None:
    if not os.path.isdir(input_folder):
        raise FileNotFoundError(f"Input PDF folder not found: {input_folder}")
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    os.makedirs(output_folder, exist_ok=True)
    df = pd.read_excel(excel_path, engine="openpyxl")

    columns = {
        "pid": require_column(
            df,
            ["P&ID DRG NO.", "P&ID DRG NO", "P&ID no.", "P&ID no", "PID"],
            "P&ID",
        ),
        "tag_type": find_column(df, ["TAG TYPE", "Tag Type", "tag_type"]),
        "box_id": find_column(df, ["BOX ID", "Box ID", "box_id"]),
        "page_no": find_column(df, ["Page No.", "Page No", "Page", "page_no"]),
        "x1": require_column(df, ["X1", "x1"], "X1"),
        "y1": require_column(df, ["Y1", "y1"], "Y1"),
        "x2": require_column(df, ["X2", "x2"], "X2"),
        "y2": require_column(df, ["Y2", "y2"], "Y2"),
    }

    df["_normalized_pid"] = df[columns["pid"]].apply(normalize_pid)
    pdf_files = [name for name in sorted(os.listdir(input_folder)) if name.lower().endswith(".pdf")]

    for index, name in enumerate(pdf_files, start=1):
        pdf_path = os.path.join(input_folder, name)
        drawing_name = os.path.splitext(name)[0]
        file_df = df[
            (df["_normalized_pid"].str.lower() == drawing_name.lower())
            | (df["_normalized_pid"].str.upper() == drawing_name.upper())
        ]

        doc = fitz.open(pdf_path)
        drawn_count = 0

        for _, row in file_df.iterrows():
            page_index = 0
            if columns["page_no"] and not pd.isna(row[columns["page_no"]]):
                try:
                    page_index = max(0, int(row[columns["page_no"]]) - 1)
                except (TypeError, ValueError):
                    page_index = 0

            if page_index >= len(doc):
                continue

            if draw_row(doc[page_index], row, columns):
                drawn_count += 1

        output_path = os.path.join(output_folder, name)
        doc.save(output_path)
        doc.close()
        print(f"PROGRESS:{name}:{index}:{len(pdf_files)}:{drawn_count}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backplot Excel coordinates onto uploaded PDFs.")
    parser.add_argument("input_folder", help="Folder containing source PDF files.")
    parser.add_argument("excel_path", help="Excel file containing coordinates.")
    parser.add_argument("output_folder", help="Folder where backplotted PDFs are written.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        process_backplot(args.input_folder, args.excel_path, args.output_folder)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
