from __future__ import annotations

from sag.generated.SAGParser import SAGParser
from sag.generated.SAGVisitor import SAGVisitor
from sag.model import (
    ActionStatement,
    AssertStatement,
    ControlStatement,
    ErrorStatement,
    EventStatement,
    FoldStatement,
    Header,
    KnowledgeStatement,
    Message,
    QueryStatement,
    RecallStatement,
    Statement,
    SubscribeStatement,
    UnsubscribeStatement,
)


class SAGModelVisitor(SAGVisitor):

    def visitMessage(self, ctx: SAGParser.MessageContext) -> Message:
        header: Header = self.visit(ctx.header())
        statements: list[Statement] = []

        if ctx.body() is not None:
            for stmt_ctx in ctx.body().statement():
                stmt = self.visit(stmt_ctx)
                if stmt is not None:
                    statements.append(stmt)

        return Message(header=header, statements=statements)

    def visitHeader(self, ctx: SAGParser.HeaderContext) -> Header:
        version = int(ctx.version().INT().getText())
        message_id = ctx.msgId().IDENT().getText()
        source = ctx.src().IDENT().getText()
        destination = ctx.dst().IDENT().getText()
        timestamp = int(ctx.timestamp().INT().getText())

        correlation = None
        if ctx.correlation() is not None:
            corr_ident = ctx.correlation().IDENT()
            corr_text = corr_ident.getText() if corr_ident is not None else None
            if corr_text is not None and corr_text != "-":
                correlation = corr_text

        ttl = None
        if ctx.ttl() is not None:
            ttl = int(ctx.ttl().INT().getText())

        return Header(
            version=version,
            message_id=message_id,
            source=source,
            destination=destination,
            timestamp=timestamp,
            correlation=correlation,
            ttl=ttl,
        )

    def visitActionStmt(self, ctx: SAGParser.ActionStmtContext) -> Statement:
        verb_call_ctx = ctx.verbCall()
        verb = verb_call_ctx.IDENT().getText()

        args: list = []
        named_args: dict = {}

        if verb_call_ctx.argList() is not None:
            for arg_ctx in verb_call_ctx.argList().arg():
                if arg_ctx.namedArg() is not None:
                    name = arg_ctx.namedArg().IDENT().getText()
                    value = self.visit(arg_ctx.namedArg().value())
                    named_args[name] = value
                else:
                    value = self.visit(arg_ctx.value())
                    args.append(value)

        policy = None
        policy_expr = None
        if ctx.policyClause() is not None:
            policy = ctx.policyClause().IDENT().getText()
            if ctx.policyClause().expr() is not None:
                policy_expr = ctx.policyClause().expr().getText()

        priority = None
        if ctx.priorityClause() is not None:
            priority = ctx.priorityClause().PRIORITY().getText()

        reason = None
        if ctx.reasonClause() is not None:
            if ctx.reasonClause().STRING() is not None:
                reason = _unquote(ctx.reasonClause().STRING().getText())
            elif ctx.reasonClause().expr() is not None:
                reason = ctx.reasonClause().expr().getText()

        return ActionStatement(
            verb=verb,
            args=args,
            named_args=named_args,
            policy=policy,
            policy_expr=policy_expr,
            priority=priority,
            reason=reason,
        )

    def visitQueryStmt(self, ctx: SAGParser.QueryStmtContext) -> Statement:
        expr = self.visit(ctx.expr())
        constraint = None
        if ctx.constraint() is not None:
            constraint = self.visit(ctx.constraint().expr())
        return QueryStatement(expression=expr, constraint=constraint)

    def visitAssertStmt(self, ctx: SAGParser.AssertStmtContext) -> Statement:
        path = ctx.path().getText()
        value = self.visit(ctx.value())
        return AssertStatement(path=path, value=value)

    def visitControlStmt(self, ctx: SAGParser.ControlStmtContext) -> Statement:
        condition = self.visit(ctx.expr())
        then_stmt = self.visit(ctx.statement(0))
        else_stmt = None
        if len(ctx.statement()) > 1:
            else_stmt = self.visit(ctx.statement(1))
        return ControlStatement(condition=condition, then_statement=then_stmt, else_statement=else_stmt)

    def visitEventStmt(self, ctx: SAGParser.EventStmtContext) -> Statement:
        event_name = ctx.IDENT().getText()
        args: list = []
        named_args: dict = {}

        if ctx.argList() is not None:
            for arg_ctx in ctx.argList().arg():
                if arg_ctx.namedArg() is not None:
                    name = arg_ctx.namedArg().IDENT().getText()
                    value = self.visit(arg_ctx.namedArg().value())
                    named_args[name] = value
                else:
                    value = self.visit(arg_ctx.value())
                    args.append(value)

        return EventStatement(event_name=event_name, args=args, named_args=named_args)

    def visitErrorStmt(self, ctx: SAGParser.ErrorStmtContext) -> Statement:
        error_code = ctx.IDENT().getText()
        message = None
        if ctx.STRING() is not None:
            message = _unquote(ctx.STRING().getText())
        return ErrorStatement(error_code=error_code, message=message)

    def visitFoldStmt(self, ctx: SAGParser.FoldStmtContext) -> Statement:
        fold_id = ctx.IDENT().getText()
        summary = _unquote(ctx.STRING().getText())
        state = None
        if ctx.object_() is not None:
            state = self._visit_object_rule(ctx.object_())
        return FoldStatement(fold_id=fold_id, summary=summary, state=state)

    def visitRecallStmt(self, ctx: SAGParser.RecallStmtContext) -> Statement:
        fold_id = ctx.IDENT().getText()
        return RecallStatement(fold_id=fold_id)

    def visitSubStmt(self, ctx: SAGParser.SubStmtContext) -> Statement:
        topic = self._extract_topic(ctx.topicExpr())
        filter_expr = None
        if ctx.expr() is not None:
            filter_expr = ctx.expr().getText()
        return SubscribeStatement(topic=topic, filter_expr=filter_expr)

    def visitUnsubStmt(self, ctx: SAGParser.UnsubStmtContext) -> Statement:
        topic = self._extract_topic(ctx.topicExpr())
        return UnsubscribeStatement(topic=topic)

    def visitKnowStmt(self, ctx: SAGParser.KnowStmtContext) -> Statement:
        topic = self._extract_topic(ctx.topicExpr())
        value = self.visit(ctx.value())
        version = int(ctx.INT().getText())
        return KnowledgeStatement(topic=topic, value=value, version=version)

    def _extract_topic(self, ctx) -> str:
        if ctx.TOPIC_PATTERN() is not None:
            return ctx.TOPIC_PATTERN().getText()
        return ctx.IDENT().getText()

    def _visit_object_rule(self, ctx) -> dict:
        result = {}
        if ctx.member() is not None:
            for member_ctx in ctx.member():
                key = _unquote(member_ctx.STRING().getText())
                value = self.visit(member_ctx.value())
                result[key] = value
        return result

    # --- Value visitors ---

    def visitValString(self, ctx: SAGParser.ValStringContext):
        return _unquote(ctx.STRING().getText())

    def visitValInt(self, ctx: SAGParser.ValIntContext):
        return int(ctx.INT().getText())

    def visitValFloat(self, ctx: SAGParser.ValFloatContext):
        return float(ctx.FLOAT().getText())

    def visitValBool(self, ctx: SAGParser.ValBoolContext):
        return ctx.BOOL().getText() == "true"

    def visitValNull(self, ctx: SAGParser.ValNullContext):
        return None

    def visitValPath(self, ctx: SAGParser.ValPathContext):
        return ctx.path().getText()

    def visitValList(self, ctx: SAGParser.ValListContext):
        result = []
        if ctx.list_().value() is not None:
            for value_ctx in ctx.list_().value():
                result.append(self.visit(value_ctx))
        return result

    def visitValObject(self, ctx: SAGParser.ValObjectContext):
        result = {}
        if ctx.object_().member() is not None:
            for member_ctx in ctx.object_().member():
                key = _unquote(member_ctx.STRING().getText())
                value = self.visit(member_ctx.value())
                result[key] = value
        return result

    # --- Expression visitors (return raw text, not evaluated) ---

    def visitOrExpr(self, ctx: SAGParser.OrExprContext):
        return ctx.getText()

    def visitAndExpr(self, ctx: SAGParser.AndExprContext):
        return ctx.getText()

    def visitRelExpr(self, ctx: SAGParser.RelExprContext):
        return ctx.getText()

    def visitAddExpr(self, ctx: SAGParser.AddExprContext):
        return ctx.getText()

    def visitMulExpr(self, ctx: SAGParser.MulExprContext):
        return ctx.getText()

    def visitPrimaryExpr(self, ctx: SAGParser.PrimaryExprContext):
        return self.visit(ctx.primary())

    def visitPrimary(self, ctx: SAGParser.PrimaryContext):
        if ctx.value() is not None:
            return self.visit(ctx.value())
        if ctx.expr() is not None:
            return self.visit(ctx.expr())
        return None


def _unquote(quoted: str) -> str:
    if quoted.startswith('"') and quoted.endswith('"'):
        return (
            quoted[1:-1]
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
        )
    return quoted
