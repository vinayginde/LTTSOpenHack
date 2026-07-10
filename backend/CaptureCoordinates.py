import argparse
import json
import os
import re
import sys
import tempfile
from typing import Dict, List, Optional, Set, Tuple
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

import fitz
import pandas as pd

try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None
    Image = None

RESTRICTED_CONTENTS = ['"', '-', '.', '°', '/', '\\', ',', '(', ')']
INSTRUMENT_CANDIDATE_PATTERN = r'^[A-Z]\d+[A-Z]\d+$'
AZURE_OPENAI_API_KEY = "09b491b9a1fd4e19ae02a890d1b24473"
AZURE_OPENAI_CHAT_COMPLETIONS_URL = (
    "https://apim-foundry-prod-ltts.azure-api.net/gpt5-mini/deployments/"
    "gpt-5-mini/chat/completions?api-version=2024-12-01-preview"
)
NOISE_SPECIAL_PATTERN = re.compile(r"[@#%~*`^{}\[\]<>|]+")
ONLY_PUNCTUATION_PATTERN = re.compile(r"^[\W_]+$")
GPT_CLEANING_BATCH_SIZE = 80


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


def extract_text_objects_from_pdf_with_ocr(pdf_path: str, pid_no: str, starting_id: int = 1) -> List[Dict[str, object]]:
    """Extract text objects and bounding boxes from a PDF using Tesseract OCR."""
    if pytesseract is None or Image is None:
        print("Warning: pytesseract and Pillow are not available; falling back to standard PDF text extraction.", file=sys.stderr)
        return extract_text_objects_from_pdf(pdf_path, pid_no, starting_id)

    try:
        import shutil
        if not shutil.which("tesseract"):
            print("Warning: Tesseract executable not found; falling back to standard PDF text extraction.", file=sys.stderr)
            return extract_text_objects_from_pdf(pdf_path, pid_no, starting_id)
    except Exception:
        return extract_text_objects_from_pdf(pdf_path, pid_no, starting_id)

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
        pix = page.get_pixmap(matrix=fitz.Matrix(5, 5), alpha=False)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_image:
            temp_path = tmp_image.name

        try:
            pix.save(temp_path)
            data = pytesseract.image_to_data(Image.open(temp_path), output_type=pytesseract.Output.DICT, config="--psm 12")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        words = data.get("text", [])
        lefts = data.get("left", [])
        tops = data.get("top", [])
        widths = data.get("width", [])
        heights = data.get("height", [])
        confs = data.get("conf", [])

        for index, text in enumerate(words):
            cleaned = str(text).strip()
            if not cleaned:
                continue

            try:
                conf = int(confs[index]) if index < len(confs) else 0
            except (TypeError, ValueError):
                conf = 0

            if conf < 30:
                print(cleaned, conf)

            try:
                x1 = float(lefts[index])
                y1 = float(tops[index])
                x2 = x1 + float(widths[index])
                y2 = y1 + float(heights[index])
            except (TypeError, ValueError, IndexError):
                continue

            tag_type = classify_text(cleaned)
            if not tag_type and not is_valid_instrument_candidate(cleaned, pid_no):
                continue

            print(f"OCR_TEXT:{pid_no}:{page_no}:{cleaned}", flush=True)
            rows.append(
                {
                    "P&ID no.": pid_no,
                    "Text": cleaned,
                    "Box ID": box_id,
                    "Tag Type": tag_type or "Instrument",
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


def get_text_column(df: pd.DataFrame) -> str:
    for column in df.columns:
        if str(column).strip().lower() == "text":
            return column
    raise ValueError('Excel output is missing a "Text" or "TEXT" column.')


def is_local_noise_text(value: object) -> bool:
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "no text detected"}:
        return True
    if NOISE_SPECIAL_PATTERN.search(text):
        return True
    if ONLY_PUNCTUATION_PATTERN.fullmatch(text):
        return True
    return False


def extract_response_text(response_json: Dict[str, object]) -> str:
    choices = response_json.get("choices", [])
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content

    direct_text = response_json.get("output_text")
    if isinstance(direct_text, str):
        return direct_text

    parts: List[str] = []
    for output_item in response_json.get("output", []):
        if not isinstance(output_item, dict):
            continue
        for content_item in output_item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                parts.append(text)

    return "\n".join(parts)


def parse_json_object(raw_text: str) -> Dict[str, object]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError("GPT cleaner returned JSON that is not an object.")
    return parsed


def get_azure_openai_api_key() -> str:
    return AZURE_OPENAI_API_KEY.strip() or os.getenv("AZURE_OPENAI_API_KEY", "").strip()


def call_gpt_cleaner(batch: List[Dict[str, object]]) -> Set[int]:
    api_key = get_azure_openai_api_key()
    if not api_key:
        print("Warning: Azure OpenAI API key not configured; GPT cleaning step skipped.", file=sys.stderr)
        return set()

    prompt_rows = [
        {
            "row_id": row["row_id"],
            "text": row["text"],
            "tag_type": row.get("tag_type", ""),
        }
        for row in batch
    ]

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You clean coordinate-extraction rows for P&ID drawings. "
                    "Return strict JSON only. Remove rows when the text is an English dictionary "
                    "word or ordinary English phrase, random OCR noise, standalone punctuation, "
                    "or contains unnecessary special characters such as @, #, %, ~, or *. "
                    "Keep likely engineering tags, equipment identifiers, pipe runs, and instrument "
                    "codes, especially values containing meaningful letters with digits, hyphens, "
                    "slashes, or quotation marks."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Classify these rows. Return exactly this shape: "
                    '{"remove_row_ids":[1,2],"keep_row_ids":[3]}. '
                    f"Rows: {json.dumps(prompt_rows, ensure_ascii=True)}"
                ),
            },
        ],
    }

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    req = urllib_request.Request(
        AZURE_OPENAI_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=120) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI cleaner failed: HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Azure OpenAI cleaner failed: {exc}") from exc

    response_text = extract_response_text(response_data)
    parsed = parse_json_object(response_text)
    remove_ids = parsed.get("remove_row_ids", [])
    if not isinstance(remove_ids, list):
        raise ValueError("GPT cleaner response is missing remove_row_ids list.")

    return {int(row_id) for row_id in remove_ids}


def clean_excel_rows_with_gpt(df: pd.DataFrame) -> pd.DataFrame:
    text_column = get_text_column(df)
    tag_column = next((col for col in df.columns if str(col).strip().lower() == "tag type"), None)

    local_keep_mask = ~df[text_column].apply(is_local_noise_text)
    locally_removed = int((~local_keep_mask).sum())
    filtered_df = df.loc[local_keep_mask].copy()

    rows_for_gpt: List[Dict[str, object]] = []
    for row_id, (_, row) in enumerate(filtered_df.iterrows(), start=1):
        rows_for_gpt.append(
            {
                "row_id": row_id,
                "text": str(row[text_column]).strip(),
                "tag_type": str(row[tag_column]).strip() if tag_column else "",
            }
        )

    gpt_remove_ids: Set[int] = set()
    if get_azure_openai_api_key():
        for start in range(0, len(rows_for_gpt), GPT_CLEANING_BATCH_SIZE):
            batch = rows_for_gpt[start:start + GPT_CLEANING_BATCH_SIZE]
            if not batch:
                continue
            gpt_remove_ids.update(call_gpt_cleaner(batch))
    else:
        print("Warning: Azure OpenAI API key not configured; GPT cleaning step skipped.", file=sys.stderr)

    if gpt_remove_ids:
        row_id_by_index = {
            index: row["row_id"]
            for index, row in zip(filtered_df.index, rows_for_gpt)
        }
        gpt_keep_mask = filtered_df.index.to_series().map(
            lambda index: row_id_by_index[index] not in gpt_remove_ids
        )
        filtered_df = filtered_df.loc[gpt_keep_mask].copy()

    print(
        f"Cleaning removed {locally_removed + len(gpt_remove_ids)} rows "
        f"({locally_removed} local, {len(gpt_remove_ids)} GPT).",
        flush=True,
    )
    return filtered_df


def process_folder(
    input_folder: str,
    output_file: str,
    copilot_excel: Optional[str] = None,
    use_ocr: bool = False,
    clean_with_gpt: bool = True,
) -> None:
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

        generic_rows = (
            extract_text_objects_from_pdf_with_ocr(pdf_path, pid_no, starting_id=1)
            if use_ocr
            else extract_text_objects_from_pdf(pdf_path, pid_no, starting_id=1)
        )
        output_rows.extend(generic_rows)

        instrument_rows: List[Dict[str, object]] = []
        if not copilot_rows:
            instrument_rows = extract_instrument_objects_from_pdf(pdf_path, pid_no, starting_id=1)
            output_rows.extend(instrument_rows)

        if not generic_rows and not instrument_rows and not copilot_rows:
            output_rows.append(
                {
                    "P&ID no.": pid_no,
                    "Text": "No text detected",
                    "Tag Type": "Instrument",
                    "Box ID": len(output_rows) + 1,
                    "X1": 0,
                    "Y1": 0,
                    "X2": 0,
                    "Y2": 0,
                    "Page No.": 1,
                }
            )

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

    if clean_with_gpt:
        df = clean_excel_rows_with_gpt(df)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="capture_coordinates")

    print(f"Exported {len(df)} rows to {output_file}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
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
    parser.add_argument(
        "--use-ocr",
        action="store_true",
        help="Use Tesseract OCR for coordinate extraction when PDFs are non-searchable.",
    )
    parser.add_argument(
        "--skip-gpt-cleaning",
        "--skip-openai-cleaning",
        dest="skip_gpt_cleaning",
        action="store_true",
        help="Skip GPT cleaning of the generated Excel rows.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    try:
        process_folder(
            args.input_folder,
            args.output_file,
            copilot_excel=args.copilot_excel,
            use_ocr=args.use_ocr,
            clean_with_gpt=not args.skip_gpt_cleaning,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
