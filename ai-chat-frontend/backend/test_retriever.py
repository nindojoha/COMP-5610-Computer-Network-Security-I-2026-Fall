import unittest

from backend.retriever import (
    calculate_relevance_score,
    retrieve_relevant_chunks,
    split_document,
)


class RetrieverTests(unittest.TestCase):

    def setUp(self):
        """
        Create sample course information that can be reused
        by multiple retrieval tests.
        """

        self.course_document = """
        COMP 5610 Computer and Network Security I.

        Homework 1 is due on November 5.

        The midterm exam will take place on November 10.
        Students should review network security, encryption,
        authentication, and access control.

        The final project is due on December 1.
        The final project requires a working AI agent,
        security testing, and an HTTPS web interface.
        """

    def test_document_is_split_into_chunks(self):
        """
        Verify that a large document can be divided into
        smaller searchable chunks.
        """

        chunks = split_document(
            self.course_document,
            chunk_size=100,
            overlap=20,
        )

        # The document should produce more than one chunk.
        self.assertGreater(
            len(chunks),
            1,
        )

    def test_relevance_score(self):
        """
        Verify that related text receives a higher
        relevance score than unrelated text.
        """

        score = calculate_relevance_score(
            "When is the midterm exam?",
            "The midterm exam is November 10.",
        )

        # Words such as "midterm" and "exam"
        # should create a positive relevance score.
        self.assertGreater(
            score,
            0,
        )

    def test_retrieve_midterm_information(self):
        """
        Verify that the retriever finds information
        related to the student's midterm question.
        """

        results = retrieve_relevant_chunks(
            "When is the midterm exam?",
            self.course_document,
            top_k=2,
        )

        # Combine the returned chunks so the test
        # can easily search the complete result.
        combined_results = " ".join(results)

        self.assertIn(
            "November 10",
            combined_results,
        )

    def test_retrieve_project_information(self):
        """
        Verify that a question about the final project
        retrieves the project section.
        """

        results = retrieve_relevant_chunks(
            "What does the final project require?",
            self.course_document,
            top_k=2,
        )

        combined_results = " ".join(results)

        self.assertIn(
            "HTTPS",
            combined_results,
        )

    def test_empty_question_rejected(self):
        """
        Verify that an empty question cannot be sent
        to the retrieval system.
        """

        with self.assertRaises(ValueError):
            retrieve_relevant_chunks(
                "",
                self.course_document,
            )


if __name__ == "__main__":
    # Run the tests when this file is executed directly.
    unittest.main()