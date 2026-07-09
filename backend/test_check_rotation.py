import tempfile
import unittest
from pathlib import Path

import fitz
import pandas as pd

from backend.CheckRotation import check_rotated


class CheckRotatedTests(unittest.TestCase):
    def test_counts_rotated_pdf_and_writes_excel(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            pdf_dir = tmp_path / "pdfs"
            pdf_dir.mkdir()

            pdf_path = pdf_dir / "sample_001.pdf"
            doc = fitz.open()
            page1 = doc.new_page()
            page1.insert_text((72, 72), "sample")
            page1.set_rotation(90)
            page2 = doc.new_page()
            page2.insert_text((72, 120), "page two")
            doc.save(pdf_path)
            doc.close()

            excel_path = tmp_path / "files.xlsx"
            pd.DataFrame({"file": ["001"]}).to_excel(excel_path, index=False)

            output_path = tmp_path / "rotated.xlsx"
            result = check_rotated(str(pdf_dir), str(excel_path), str(output_path))

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["multi_page_count"], 1)
            self.assertEqual(result["files"][0]["filename"], "sample_001.pdf")
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
