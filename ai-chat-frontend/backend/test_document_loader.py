import unittest

from backend.document_loader import load_document


class DocumentLoaderTests(unittest.TestCase):

    def test_txt_document(self):
        """A valid TXT document should load and return its text."""

        # Create a small sample syllabus as raw bytes.
        data = (
            b"COMP 5610\n"
            b"Midterm Exam: November 10\n"
            b"Final Project: December 1"
        )

        result = load_document(
            "syllabus.txt",
            data
        )

        # Confirm that expected course information was extracted.
        self.assertIn(
            "Midterm Exam: November 10",
            result
        )

    def test_empty_txt_rejected(self):
        """An empty TXT file should be rejected."""

        with self.assertRaises(ValueError):
            load_document(
                "empty.txt",
                b""
            )

    def test_invalid_extension_rejected(self):
        """Unsupported file types should not be processed."""

        with self.assertRaises(ValueError):
            load_document(
                "script.py",
                b"print('hello')"
            )


# Run the tests when this file is executed directly.
if __name__ == "__main__":
    unittest.main()