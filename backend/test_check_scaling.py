import tempfile
import unittest
from pathlib import Path

import fitz

from backend.CheckScaling import check_scaling


class CheckScalingTests(unittest.TestCase):
    def test_counts_scaled_in_and_scaled_out_against_reference(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            pdf_dir = tmp_path / "pdfs"
            pdf_dir.mkdir()

            reference_path = pdf_dir / "reference.pdf"
            doc = fitz.open()
            doc.new_page(width=500, height=700)
            doc.save(reference_path)
            doc.close()

            scaled_in_path = pdf_dir / "scaled_in.pdf"
            doc = fitz.open()
            doc.new_page(width=200, height=300)
            doc.save(scaled_in_path)
            doc.close()

            scaled_out_path = pdf_dir / "scaled_out.pdf"
            doc = fitz.open()
            doc.new_page(width=800, height=1000)
            doc.save(scaled_out_path)
            doc.close()

            result = check_scaling(str(pdf_dir), "reference.pdf")

            self.assertEqual(result["scaled_in_count"], 1)
            self.assertEqual(result["scaled_out_count"], 1)
            self.assertEqual(result["files"][0]["filename"], "scaled_in.pdf")
            self.assertEqual(result["files"][1]["filename"], "scaled_out.pdf")


if __name__ == "__main__":
    unittest.main()
