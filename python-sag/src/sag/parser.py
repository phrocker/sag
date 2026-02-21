from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from sag.exceptions import SAGParseException
from sag.generated.SAGLexer import SAGLexer
from sag.generated.SAGParser import SAGParser
from sag.model import Message
from sag.visitor import SAGModelVisitor


class _ThrowingErrorListener(ErrorListener):
    INSTANCE: _ThrowingErrorListener

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise SAGParseException(f"Syntax error at line {line}:{column} - {msg}")


_ThrowingErrorListener.INSTANCE = _ThrowingErrorListener()


class SAGMessageParser:
    @staticmethod
    def parse(text: str) -> Message:
        try:
            input_stream = InputStream(text)
            lexer = SAGLexer(input_stream)
            lexer.removeErrorListeners()
            lexer.addErrorListener(_ThrowingErrorListener.INSTANCE)

            tokens = CommonTokenStream(lexer)
            parser = SAGParser(tokens)
            parser.removeErrorListeners()
            parser.addErrorListener(_ThrowingErrorListener.INSTANCE)

            tree = parser.message()
            visitor = SAGModelVisitor()
            return visitor.visit(tree)
        except SAGParseException:
            raise
        except Exception as e:
            raise SAGParseException(f"Failed to parse SAG message: {e}", cause=e) from e
