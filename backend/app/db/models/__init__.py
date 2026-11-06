"""ORM models. Import every model here so Alembic can see it."""

from app.db.models.access import Audience, RuleKind, SpaceAccessRule
from app.db.models.account_link import AccountLink
from app.db.models.alert import Alert, AlertEvent, AlertSource, AlertState, Operator
from app.db.models.benchmark import (
    BenchmarkGate,
    BenchmarkItem,
    BenchmarkResult,
    BenchmarkRun,
    Outcome,
    RunStatus,
)
from app.db.models.chat import (
    FINISHED_WITH_CONTEXT,
    Conversation,
    ConversationShare,
    Message,
    MessageStatus,
)
from app.db.models.connection import AuditEvent, ConnectionStatus, DbConnection
from app.db.models.dashboard import (
    Dashboard,
    DashboardItem,
    Frequency,
    Report,
    ReportFormat,
    ReportItem,
    ReportRun,
    ReportRunStatus,
)
from app.db.models.knowledge import (
    Chunk,
    ChunkType,
    Document,
    DocumentStatus,
    ExpressionTest,
    ExpressionType,
    ExpressionVersion,
    KnowledgeItem,
    KnowledgeKind,
    SqlExpression,
)
from app.db.models.llm_call import LLMCall
from app.db.models.mail import MailSettings, SavedRecipient
from app.db.models.metadata import ColumnValue, JoinSource, Relationship, SpaceColumn, SpaceJoin
from app.db.models.notification import Notification
from app.db.models.notification_settings import NotificationPreference, NotificationSettings
from app.db.models.space import SourceType, Space, SpaceMember, SpaceRole, SpaceTable
from app.db.models.user import RefreshToken, Role, User

__all__ = [
    "FINISHED_WITH_CONTEXT",
    "AccountLink",
    "Alert",
    "AlertEvent",
    "AlertSource",
    "AlertState",
    "Audience",
    "AuditEvent",
    "BenchmarkGate",
    "BenchmarkItem",
    "BenchmarkResult",
    "BenchmarkRun",
    "Chunk",
    "ChunkType",
    "ColumnValue",
    "ConnectionStatus",
    "Conversation",
    "ConversationShare",
    "Dashboard",
    "DashboardItem",
    "DbConnection",
    "Document",
    "DocumentStatus",
    "ExpressionTest",
    "ExpressionType",
    "ExpressionVersion",
    "Frequency",
    "JoinSource",
    "KnowledgeItem",
    "KnowledgeKind",
    "LLMCall",
    "MailSettings",
    "Message",
    "MessageStatus",
    "Notification",
    "NotificationPreference",
    "NotificationSettings",
    "Operator",
    "Outcome",
    "RefreshToken",
    "Relationship",
    "Report",
    "ReportFormat",
    "ReportItem",
    "ReportRun",
    "ReportRunStatus",
    "Role",
    "RuleKind",
    "RunStatus",
    "SavedRecipient",
    "SourceType",
    "Space",
    "SpaceAccessRule",
    "SpaceColumn",
    "SpaceJoin",
    "SpaceMember",
    "SpaceRole",
    "SpaceTable",
    "SqlExpression",
    "User",
]
