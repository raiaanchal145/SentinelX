import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def _by_value(enum_cls):
    """
    values_callable for sa.Enum(): SQLAlchemy's Enum type stores each
    Python enum member's *name* in the database by default, not its
    *value* -- a well-known gotcha. IncidentStatus and TicketStatus below
    deliberately have lowercase member names but uppercase values (e.g.
    `new = "NEW"`) to match the uppercase status lists in the project
    docs, so those two columns must pass this in to make SQLAlchemy
    actually use `.value`; every other enum here has name == value, so
    the distinction is harmless for them but this helper isn't needed.
    """
    return [e.value for e in enum_cls]


class AdminLevel(str, enum.Enum):
    super_admin = "super_admin"
    organization_admin = "organization_admin"
    # Platform-side SOC staff -- an admin_level, not a UserRole, since
    # they authenticate through the same table/flow as super_admin and
    # are never scoped to a single organization by a foreign key (their
    # organization_id is NULL, same check-constraint shape as
    # super_admin). Which organizations they can see comes from
    # soc_organization_assignments, not from organization_id.
    platform_soc_analyst = "platform_soc_analyst"


class OrganizationStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    archived = "archived"


class SocMode(str, enum.Enum):
    managed = "managed"
    in_house = "in_house"


class UserRole(str, enum.Enum):
    soc_analyst = "soc_analyst"
    security_manager = "security_manager"
    it_developer = "it_developer"
    auditor = "auditor"


class ActorType(str, enum.Enum):
    """
    Who/what performed an action. Used for polymorphic (actor_type,
    actor_id) pairs where an admin, a user, an AI agent, or the system
    itself can all be the actor -- actor_id is a plain UUID with no FK,
    since which table it points into depends on actor_type.
    """

    admin = "admin"
    user = "user"
    ai_agent = "ai_agent"
    system = "system"


class AssetCriticality(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class AssetType(str, enum.Enum):
    server = "server"
    workstation = "workstation"
    laptop = "laptop"
    network_device = "network_device"
    firewall = "firewall"
    application = "application"
    api = "api"
    database = "database"
    container = "container"
    cloud_resource = "cloud_resource"


class EventSourceType(str, enum.Enum):
    linux_auth = "linux_auth"
    application = "application"
    docker = "docker"
    network = "network"
    custom_json = "custom_json"
    test = "test"


class EventSeverity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class DetectionRuleType(str, enum.Enum):
    threshold = "threshold"
    sequence = "sequence"
    pattern = "pattern"
    statistical = "statistical"


class AlertStatus(str, enum.Enum):
    new = "new"
    triaged = "triaged"
    investigating = "investigating"
    dismissed = "dismissed"
    converted = "converted"


class IncidentStatus(str, enum.Enum):
    new = "NEW"
    triaged = "TRIAGED"
    investigating = "INVESTIGATING"
    containment = "CONTAINMENT"
    remediation = "REMEDIATION"
    verification = "VERIFICATION"
    resolved = "RESOLVED"
    closed = "CLOSED"
    false_positive = "FALSE_POSITIVE"
    duplicate = "DUPLICATE"
    escalated = "ESCALATED"
    reopened = "REOPENED"


class TicketStatus(str, enum.Enum):
    open = "OPEN"
    triaged = "TRIAGED"
    assigned = "ASSIGNED"
    acknowledged = "ACKNOWLEDGED"
    investigating = "INVESTIGATING"
    remediation = "REMEDIATION"
    verification = "VERIFICATION"
    resolved = "RESOLVED"
    closed = "CLOSED"


class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"
    blocked = "blocked"


class ApprovalRiskLevel(str, enum.Enum):
    read_only = "read_only"
    low = "low"
    high = "high"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class VerificationResult(str, enum.Enum):
    verified = "verified"
    failed = "failed"
    reopened = "reopened"


class EvidenceType(str, enum.Enum):
    log = "log"
    file = "file"
    screenshot = "screenshot"
    note = "note"
    command_output = "command_output"


class AgentType(str, enum.Enum):
    triage = "triage"
    context = "context"
    threat_analysis = "threat_analysis"
    incident = "incident"
    report = "report"
    orchestrator = "orchestrator"


class NotificationChannel(str, enum.Enum):
    in_app = "in_app"
    email = "email"


class ReportType(str, enum.Enum):
    incident = "incident"
    management = "management"
    sla = "sla"
    audit = "audit"


# ---------------------------------------------------------------------------
# Organizations, admins, users, teams -- identity and tenancy
# ---------------------------------------------------------------------------


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120))
    environment: Mapped[str | None] = mapped_column(String(60))
    timezone: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, name="organization_status"),
        nullable=False,
        default=OrganizationStatus.active,
        index=True,
    )
    # managed: this organization's alerts/incidents are worked by
    # platform SOC staff (soc_organization_assignments). in_house: the
    # organization's own soc_analyst users work them, and the soc/
    # incidents modules become assignable to that role.
    soc_mode: Mapped[SocMode] = mapped_column(
        Enum(SocMode, name="soc_mode"), nullable=False, default=SocMode.managed
    )
    # NULL = unlimited. Counts active members + owners + pending invitations.
    max_members: Mapped[int | None] = mapped_column(Integer)
    # "self_signup" | "platform_admin" -- how the organization came to exist.
    created_via: Mapped[str] = mapped_column(String(20), nullable=False, default="self_signup")
    approved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)
    # Nullable: orgs created before this column existed (or a hypothetical
    # future system-seeded org) have no creating admin on file.
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    admins: Mapped[list["Admin"]] = relationship(
        back_populates="organization", foreign_keys="Admin.organization_id"
    )
    users: Mapped[list["User"]] = relationship(back_populates="organization")
    assets: Mapped[list["Asset"]] = relationship(back_populates="organization")


class Admin(Base):
    """
    Platform/organization administrators -- split out of `users` so admin
    auth (super_admin has organization_id NULL; organization_admin always
    has one) never shares a table, a role enum, or a query path with
    ordinary analyst/developer/auditor accounts in `users`.
    """

    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    admin_level: Mapped[AdminLevel] = mapped_column(
        Enum(AdminLevel, name="admin_level"), default=AdminLevel.organization_admin
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    # Same email-verification / lockout / reset shape as User -- see the
    # comments there, this is deliberately kept identical.
    is_verified: Mapped[bool] = mapped_column(default=False)
    verification_code: Mapped[str | None] = mapped_column(String(10))
    verification_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    password_reset_code: Mapped[str | None] = mapped_column(String(10))
    password_reset_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization | None"] = relationship(
        back_populates="admins", foreign_keys=[organization_id]
    )

    __table_args__ = (
        CheckConstraint(
            "(admin_level IN ('super_admin', 'platform_soc_analyst') AND organization_id IS NULL) OR "
            "(admin_level = 'organization_admin' AND organization_id IS NOT NULL)",
            name="ck_admins_level_matches_org",
        ),
    )


class AccountEmail(Base):
    """
    Enforces "email unique across admins AND users" at the database
    level. Postgres has no way to put a single UNIQUE constraint across
    two different tables, so every admin/user row also gets exactly one
    row here, written in the same transaction as the admin/user insert.
    The register endpoint checks/reserves an email here instead of
    querying admins and users separately, which is also what makes the
    cross-table check race-safe under concurrent signups.
    """

    __tablename__ = "account_emails"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "admin" | "user"
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.soc_analyst
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    # Email verification. An account cannot log in until is_verified is True.
    # verification_code/verification_code_expires_at hold the current
    # outstanding 6-digit code -- used both to finish registration and,
    # if is_verified gets flipped back to False by the lockout below, to
    # re-verify before logging in again.
    is_verified: Mapped[bool] = mapped_column(default=False)
    verification_code: Mapped[str | None] = mapped_column(String(10))
    verification_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Wrong-password counter. Reset to 0 on any successful login or
    # password reset; hitting 3 forces is_verified back to False (and
    # emails a fresh code) so the account can't be logged into again
    # until it's re-verified.
    failed_login_attempts: Mapped[int] = mapped_column(default=0)

    # Forgot-password flow. Separate from verification_code above so a
    # password reset never accidentally re-triggers/clears the account
    # verification state.
    password_reset_code: Mapped[str | None] = mapped_column(String(10))
    password_reset_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="users")
    team: Mapped["Team | None"] = relationship(back_populates="members")


class PendingRegistration(Base):
    """
    A registration that has been submitted but not yet email-verified.

    No row is created in `admins` or `users` here -- verify-email()
    creates the row in whichever table account_type points to, using
    `role` for a user or `admin_level` for an admin (the CHECK constraint
    below keeps exactly one of those populated). organization_name is
    used to create a brand-new organization at verify time: for an
    organization_admin signup (per the spec, self-registering as an org
    admin always creates a new org), and, since there's no "pick your
    org" UI yet, as the default for a plain user signup too (see the
    register endpoint for the exact rule).
    """

    __tablename__ = "pending_registrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    account_type: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    role: Mapped[UserRole | None] = mapped_column(Enum(UserRole, name="user_role"))
    admin_level: Mapped[AdminLevel | None] = mapped_column(Enum(AdminLevel, name="admin_level"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    organization_name: Mapped[str | None] = mapped_column(String(200))
    # Only meaningful alongside organization_name, for a self-signup
    # organization_admin -- carries the register form's optional
    # industry field across to verify_email()'s Organization creation.
    organization_industry: Mapped[str | None] = mapped_column(String(120))

    verification_code: Mapped[str] = mapped_column(String(10), nullable=False)
    verification_code_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "(account_type = 'admin' AND admin_level IS NOT NULL AND role IS NULL) OR "
            "(account_type = 'user' AND role IS NOT NULL AND admin_level IS NULL)",
            name="ck_pending_registrations_type_matches_fields",
        ),
    )


class OrganizationModule(Base):
    """
    Which modules a platform admin has switched on for an organization --
    the first (widest) layer of the effective-access calculation in
    access.py. A module with no row here is treated as disabled; the
    migration backfills every existing organization with every module
    key enabled so nothing regresses when this table is introduced.
    """

    __tablename__ = "organization_modules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "module_key", name="uq_organization_modules_org_key"),
    )


class OrganizationRoleAccess(Base):
    """
    The owner's per-role overrides of the role default map (access.py),
    bounded above by OrganizationModule. A missing row means "use the
    role default" -- rows only exist where the owner changed one.
    """

    __tablename__ = "organization_role_access"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "role", "module_key", name="uq_org_role_access_org_role_key"
        ),
    )


class UserAccessOverride(Base):
    """
    A single person's deny-only override of their role's access, the
    narrowest layer of access.py's effective-access calculation. A row
    can only ever narrow: allowed=False removes a module that org+role
    would otherwise grant; allowed=True (or no row at all) means "use
    the default" and can never grant a module the organization or the
    role does not already allow -- enforced in the service layer, since
    a bare column can't express "no wider than the layer below it."
    """

    __tablename__ = "user_access_overrides"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(40), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    set_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "module_key", name="uq_user_access_overrides_user_key"),
    )


class Invitation(Base):
    """
    The only path to create a member account, an owner account created
    by the platform, or a platform SOC analyst account. kind/status are
    plain strings (not Postgres enums) -- same lightweight-state-field
    convention as organizations.created_via and account_emails.account_type
    elsewhere in this schema.

    organization_id is NULL only for kind == "platform_soc" (a platform
    SOC analyst isn't scoped to one organization). accepted_account_type/
    accepted_account_id are a polymorphic pointer with no FK, same
    pattern as AuditLog.actor_id/target_id -- which table they point
    into depends on accepted_account_type.
    """

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # owner | member | platform_soc
    role: Mapped[UserRole | None] = mapped_column(Enum(UserRole, name="user_role"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    invited_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_account_type: Mapped[str | None] = mapped_column(String(10))
    accepted_account_id: Mapped[uuid.UUID | None] = mapped_column()

    __table_args__ = (
        Index("ix_invitations_organization_id", "organization_id"),
        # One pending invitation per (organization_id, email) for a
        # member/owner invite ...
        Index(
            "uq_invitations_pending_org_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending' AND organization_id IS NOT NULL"),
        ),
        # ... and, since platform_soc invitations have organization_id
        # NULL, one pending platform_soc invitation per email.
        Index(
            "uq_invitations_pending_email_platform",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending' AND organization_id IS NULL"),
        ),
    )


class SocOrganizationAssignment(Base):
    """
    Which platform_soc_analyst admins are assigned to which (managed)
    organizations -- this is what soc_visible_organization_ids() in
    access.py reads. That admin_id actually belongs to a
    platform_soc_analyst is enforced in the service layer: a bare FK to
    admins can't express "and admin_level = platform_soc_analyst".
    """

    __tablename__ = "soc_organization_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("admin_id", "organization_id", name="uq_soc_org_assignments_admin_org"),
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    members: Mapped[list["User"]] = relationship(back_populates="team")


class TeamMember(Base):
    """
    Explicit membership (with a role_in_team) for users who sit on more
    than one team. User.team_id stays as "primary team, used as the
    assignment default"; this table is the full many-to-many.
    """

    __tablename__ = "team_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_in_team: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),)


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    security_policy: Mapped[dict | None] = mapped_column(JSONB)
    notification_prefs: Mapped[dict | None] = mapped_column(JSONB)
    auto_ticket_threshold: Mapped[EventSeverity | None] = mapped_column(
        Enum(EventSeverity, name="event_severity")
    )
    ai_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ApiKey(Base):
    """
    Collectors/event sources authenticate with these instead of a user
    session. Only key_hash + a short display prefix (e.g. "sk_live_ab12")
    are stored -- the real key is shown once at creation and never
    persisted in full.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("event_sources.id", ondelete="SET NULL")
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Session(Base):
    """
    Refresh-token/session tracking, kept as one table since the fields
    the spec wants for "refresh_tokens" and "sessions" are identical --
    a refresh token *is* a session in this model. Access tokens stay
    stateless JWTs (app/security.py); this table exists purely so a
    session can be listed/revoked server-side later (e.g. "log out
    everywhere"). account_id has no FK since account_type picks which
    table (admins or users) it points into.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "admin" | "user"
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    # Human display name -- required. hostname is a separate, OPTIONAL
    # technical identifier (an "application"/"cloud_resource" asset may
    # not have one) -- see uq_assets_org_lower_hostname in the
    # h1a2b3c4d5e6 migration for the partial unique index that only
    # applies when it's set.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(200))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType, name="asset_type"))
    criticality: Mapped[AssetCriticality] = mapped_column(
        Enum(AssetCriticality, name="asset_criticality"),
        default=AssetCriticality.medium,
    )
    operating_system: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(150))
    # Free-text, but validated at the API layer to production/staging/
    # development -- see app/routers/assets.py's ASSET_ENVIRONMENTS.
    environment: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    # Free-text owner stays for now (existing data/UI reads it, and
    # pre-real-endpoint rows may only have this);  owner_user_id is the
    # real, now-actually-used-by-the-UI FK -- see app/routers/assets.py.
    owner: Mapped[str | None] = mapped_column(String(150))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Free-text, but validated at the API layer to active/retired -- see
    # app/routers/assets.py's ASSET_STATUSES. "retired" is the DELETE
    # endpoint's soft-delete terminal state.
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="assets")


class AssetTag(Base):
    __tablename__ = "asset_tags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (UniqueConstraint("asset_id", "tag", name="uq_asset_tags_asset_tag"),)


class EventSource(Base):
    __tablename__ = "event_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    source_type: Mapped[EventSourceType] = mapped_column(
        Enum(EventSourceType, name="event_source_type"), nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    config: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="active")
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# Event pipeline: events -> detections -> alerts -> correlations
# ---------------------------------------------------------------------------


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, name="event_severity"), default=EventSeverity.info
    )
    username: Mapped[str | None] = mapped_column(String(150))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    dedup_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    normalized_data: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        # Partition-ready: this is the hot query path (an org's event
        # timeline), so it gets a composite index up front.
        Index("ix_security_events_org_occurred_at", "organization_id", "occurred_at"),
    )


class DetectionRule(Base):
    __tablename__ = "detection_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable: built-in rules ship with the platform and aren't owned by
    # any one organization.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[DetectionRuleType] = mapped_column(
        Enum(DetectionRuleType, name="detection_rule_type"), nullable=False
    )
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, name="event_severity"), default=EventSeverity.medium
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    mitre_technique: Mapped[str | None] = mapped_column(String(20))
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    detection_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("detection_rules.id", ondelete="SET NULL")
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, name="event_severity"), default=EventSeverity.medium
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status"), default=AlertStatus.new
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, default=1)
    dedup_key: Mapped[str | None] = mapped_column(String(150), index=True)

    __table_args__ = (Index("ix_alerts_org_status", "organization_id", "status"),)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("security_events.id", ondelete="CASCADE"), primary_key=True
    )


class CorrelationRule(Base):
    __tablename__ = "correlation_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    time_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Correlation(Base):
    __tablename__ = "correlations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    correlation_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("correlation_rules.id", ondelete="SET NULL")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CorrelationAlert(Base):
    __tablename__ = "correlation_alerts"

    correlation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correlations.id", ondelete="CASCADE"), primary_key=True
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )


# ---------------------------------------------------------------------------
# Incidents and tickets
# ---------------------------------------------------------------------------


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, name="event_severity"), default=EventSeverity.medium
    )
    priority: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status", values_callable=_by_value),
        default=IncidentStatus.new,
    )
    primary_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("correlations.id", ondelete="SET NULL")
    )
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Polymorphic -- an incident can be opened by an admin, a user, or
    # created automatically by an AI agent / the system.
    created_by_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), default=ActorType.system
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column()

    __table_args__ = (Index("ix_incidents_org_status", "organization_id", "status"),)


class IncidentAlert(Base):
    __tablename__ = "incident_alerts"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("security_events.id", ondelete="CASCADE"), primary_key=True
    )


class IncidentAsset(Base):
    __tablename__ = "incident_assets"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )


class IncidentTimeline(Base):
    __tablename__ = "incident_timeline"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    entry_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    # Python attribute renamed off "metadata" -- that name is reserved by
    # SQLAlchemy's declarative Base; the DB column is still "metadata".
    entry_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)


class SlaPolicy(Base):
    __tablename__ = "sla_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    acknowledge_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolve_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    business_hours_only: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "priority", name="uq_sla_policies_org_priority"),
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Human-readable, unique per organization (e.g. "TICK-42"), not
    # globally unique -- see the uq_tickets_org_number constraint below.
    # Allocating the next number is left to the endpoint layer, which
    # isn't built yet (out of scope for this migration).
    ticket_number: Mapped[str] = mapped_column(String(30), nullable=False)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, name="event_severity"), default=EventSeverity.medium
    )
    priority: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status", values_callable=_by_value),
        default=TicketStatus.open,
    )
    assigned_team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sla_policies.id", ondelete="SET NULL")
    )
    ack_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolve_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_breached: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "ticket_number", name="uq_tickets_org_number"),
        Index("ix_tickets_org_status", "organization_id", "status"),
        Index("ix_tickets_assigned_user", "assigned_user_id"),
        Index("ix_tickets_resolve_due_at", "resolve_due_at"),
    )


class TicketAssignment(Base):
    """Assignment history -- every hand-off a ticket goes through, kept
    even after the ticket's current assignee changes again."""

    __tablename__ = "ticket_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_by_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"))
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column()
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[TicketStatus | None] = mapped_column(
        Enum(TicketStatus, name="ticket_status", values_callable=_by_value)
    )
    to_status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status", values_callable=_by_value), nullable=False
    )
    changed_by_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"))
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column()
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)


class Task(Base):
    """A remediation task under a ticket."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.open
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_approval: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AssignmentRule(Base):
    __tablename__ = "assignment_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    match_conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    assign_to_team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    priority_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    escalated_from: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    escalated_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "ticket_id IS NOT NULL OR incident_id IS NOT NULL",
            name="ck_escalations_has_target",
        ),
    )


class Approval(Base):
    """
    The human-in-the-loop gate for high-risk AI-agent (or user-initiated)
    actions: nothing described in action_payload actually executes until
    a human reviewer approves it here.
    """

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column()
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[ApprovalRiskLevel] = mapped_column(
        Enum(ApprovalRiskLevel, name="approval_risk_level"), nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), default=ApprovalStatus.pending
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # RESTRICT: evidence is part of the record of an incident and
    # shouldn't silently vanish if the incident row is ever deleted.
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL")
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, name="evidence_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Either a pointer to externally-stored content (storage_ref, e.g. a
    # file path/object key) or small inline content -- evidence doesn't
    # have to be a file (e.g. a typed note).
    storage_ref: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[dict | None] = mapped_column(JSONB)
    sha256: Mapped[str | None] = mapped_column(String(64))
    added_by_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verified_by_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column()
    method: Mapped[str | None] = mapped_column(String(120))
    result: Mapped[VerificationResult] = mapped_column(
        Enum(VerificationResult, name="verification_result"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# AI agents
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, name="agent_type"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt_version: Mapped[str | None] = mapped_column(String(30))
    allowed_tools: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # RESTRICT: an agent's definition shouldn't be deletable out from
    # under its run history.
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # What the agent was run against, e.g. target_type="alert" +
    # target_id=<alerts.id> -- polymorphic, so no FK.
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), default="running")
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class AiAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "alert" | "incident" -- polymorphic, so no FK.
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    recommended_actions: Mapped[dict | None] = mapped_column(JSONB)
    severity_suggestion: Mapped[EventSeverity | None] = mapped_column(
        Enum(EventSeverity, name="event_severity")
    )
    # Whether an analyst accepted the recommendation -- feeds an
    # "AI acceptance rate" metric later.
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ToolCallLog(Base):
    """
    Every tool call an agent attempts, whether it ran or was blocked
    pending approval -- this is what proves the permission layer
    actually ran, independent of what the agent's own output claims.
    """

    __tablename__ = "tool_call_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict | None] = mapped_column(JSONB)
    risk_level: Mapped[ApprovalRiskLevel] = mapped_column(
        Enum(ApprovalRiskLevel, name="approval_risk_level"), nullable=False
    )
    allowed: Mapped[bool] = mapped_column(nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approvals.id", ondelete="SET NULL")
    )
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# Operations: notifications, audit, reporting
# ---------------------------------------------------------------------------


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # What this notification is about, e.g. related_type="ticket" --
    # polymorphic, so no FK.
    related_type: Mapped[str | None] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID | None] = mapped_column()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditLog(Base):
    """
    Append-only. Never updated or deleted by the application -- ondelete
    is RESTRICT on organization_id so this table can't lose history out
    from under it just because an organization row is removed.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_audit_logs_org_created_at", "organization_id", "created_at"),)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, name="report_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), default=ActorType.system
    )
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column()
    content: Mapped[dict | None] = mapped_column(JSONB)
    file_ref: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SystemMetricsDaily(Base):
    """Optional pre-aggregate for the dashboard: one row per org per day."""

    __tablename__ = "system_metrics_daily"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    mttd_seconds: Mapped[int | None] = mapped_column(Integer)
    mtta_seconds: Mapped[int | None] = mapped_column(Integer)
    mttr_seconds: Mapped[int | None] = mapped_column(Integer)
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    incident_count: Mapped[int] = mapped_column(Integer, default=0)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0)
    sla_compliance_pct: Mapped[float | None] = mapped_column(Float)
