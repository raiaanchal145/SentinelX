import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    organization_admin = "organization_admin"
    soc_analyst = "soc_analyst"
    it_developer = "it_developer"
    auditor = "auditor"


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


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120))
    environment: Mapped[str | None] = mapped_column(String(60))
    timezone: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    assets: Mapped[list["Asset"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
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

    organization: Mapped["Organization | None"] = relationship(back_populates="users")


class PendingRegistration(Base):
    """
    A registration that has been submitted but not yet email-verified.

    No row in `users` is created until the OTP is confirmed -- this table
    holds everything needed to create that row at that point (name,
    password hash, role) plus the outstanding code/expiry. Re-registering
    with the same email before verifying overwrites this row instead of
    creating a duplicate.
    """

    __tablename__ = "pending_registrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.soc_analyst
    )
    verification_code: Mapped[str] = mapped_column(String(10), nullable=False)
    verification_code_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType, name="asset_type"))
    criticality: Mapped[AssetCriticality] = mapped_column(
        Enum(AssetCriticality, name="asset_criticality"),
        default=AssetCriticality.medium,
    )
    owner: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="assets")
