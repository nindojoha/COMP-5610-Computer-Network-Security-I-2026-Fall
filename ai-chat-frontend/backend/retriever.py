import re
from typing import List


# Default number of relevant text chunks that will be returned
# when searching a course document.
DEFAULT_TOP_K = 3


def split_document(
    document_text: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> List[str]:
    """
    Split a large course document into smaller overlapping chunks.

    Smaller chunks make it easier for the retrieval system to find
    the section that is most relevant to a student's question.
    """

    # Reject empty document content.
    if not document_text or not document_text.strip():
        raise ValueError("Document text cannot be empty.")

    # Make sure the chunk configuration is valid.
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than zero.")

    if overlap < 0:
        raise ValueError("Overlap cannot be negative.")

    if overlap >= chunk_size:
        raise ValueError("Overlap must be smaller than chunk size.")

    # Remove unnecessary whitespace while keeping the text readable.
    cleaned_text = re.sub(
        r"[ \t]+",
        " ",
        document_text.strip(),
    )

    chunks = []

    # Start reading from the beginning of the document.
    start = 0

    while start < len(cleaned_text):
        # Determine where the current chunk should end.
        end = start + chunk_size

        # Extract the current chunk.
        chunk = cleaned_text[start:end].strip()

        # Only store non-empty chunks.
        if chunk:
            chunks.append(chunk)

        # Move forward while keeping some overlap with the
        # previous chunk so important text is not split completely.
        start += chunk_size - overlap

    return chunks


def tokenize(text: str) -> set[str]:
    """
    Convert text into lowercase searchable words.

    This lightweight tokenizer is used by the Phase 2 prototype
    instead of requiring a larger vector database.
    """

    # Find words containing letters, numbers, and underscores.
    words = re.findall(
        r"\b\w+\b",
        text.lower(),
    )

    return set(words)


def calculate_relevance_score(
    question: str,
    chunk: str,
) -> int:
    """
    Calculate a simple relevance score between a student's
    question and a document chunk.

    The score is based on how many words appear in both texts.
    """

    # Convert the question and chunk into searchable word sets.
    question_words = tokenize(question)
    chunk_words = tokenize(chunk)

    # Count the number of words shared by both sets.
    matching_words = question_words.intersection(chunk_words)

    return len(matching_words)


def retrieve_relevant_chunks(
    question: str,
    document_text: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[str]:
    """
    Retrieve the most relevant parts of a course document
    for a student's question.

    These chunks can later be passed to Gemini as context.
    """

    # Reject an empty student question.
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    # Reject invalid result limits.
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    # Break the document into smaller searchable sections.
    chunks = split_document(document_text)

    scored_chunks = []

    # Calculate how relevant each chunk is to the question.
    for chunk in chunks:
        score = calculate_relevance_score(
            question,
            chunk,
        )

        # Only keep chunks that contain at least one
        # word related to the user's question.
        if score > 0:
            scored_chunks.append(
                (score, chunk)
            )

    # Sort results so the most relevant chunks appear first.
    scored_chunks.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    # Return only the requested number of chunks.
    return [
        chunk
        for score, chunk in scored_chunks[:top_k]
    ]