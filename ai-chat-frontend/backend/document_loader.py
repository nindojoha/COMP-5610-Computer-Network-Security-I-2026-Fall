from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from backend.security import validate_upload


def extract_text_from_txt(data: bytes) -> str:
    """Extract UTF-8 text from a TXT file."""

    # Decode the uploaded file using UTF-8.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("TXT file must use UTF-8 encoding.") from exc

    # Remove unnecessary whitespace around the document.
    text = text.strip()

    # Reject empty or unreadable text files.
    if not text:
        raise ValueError("The document does not contain readable text.")

    return text


def extract_text_from_pdf(data: bytes) -> str:
    """Extract text from a PDF document."""

    # Read the PDF directly from the uploaded bytes.
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ValueError("Unable to read the PDF file.") from exc

    pages = []

    # Extract text from each page and keep the page number.
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()

        if text:
            pages.append(
                f"[Page {page_number}]\n{text.strip()}"
            )

    # Some PDFs, such as scanned documents, may not contain extractable text.
    if not pages:
        raise ValueError(
            "The PDF does not contain extractable text."
        )

    # Combine all extracted pages into one document string.
    return "\n\n".join(pages)


def load_document(filename: str, data: bytes) -> str:
    """
    Validate and extract text from an uploaded course document.
    """

    # Check the file type and size before processing it.
    validate_upload(filename, len(data))

    extension = Path(filename).suffix.lower()

    # Use the correct extractor based on the uploaded file type.
    if extension == ".txt":
        return extract_text_from_txt(data)

    if extension == ".pdf":
        return extract_text_from_pdf(data)

    # Safety fallback in case another file type reaches this point.
    raise ValueError("Unsupported document type.")