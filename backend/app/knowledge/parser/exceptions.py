class DocumentParserError(ValueError):
    """Base error raised by the document parser boundary."""

    code = "parser_error"

    def __init__(self, message: str, *, parser_id: str = "", code: str | None = None) -> None:
        super().__init__(message)
        self.parser_id = parser_id
        self.code = code or type(self).code


class ParserNotFoundError(DocumentParserError):
    code = "parser_not_found"


class UnsupportedDocumentTypeError(DocumentParserError):
    code = "unsupported_document_type"


class EmptyParseResultError(DocumentParserError):
    code = "empty_parse_result"
