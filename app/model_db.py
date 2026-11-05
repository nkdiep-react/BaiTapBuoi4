from .database import Base

from sqlalchemy import Date, DateTime, Integer, String, Text, ForeignKey, Boolean, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone, date

# code ham lay time hien tai theo UTC
def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Define the User model
class User(Base):  
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


# Server-side login session. Only the SHA-256 hash of the cookie token is stored,
# so a database leak does not expose usable session tokens.
class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

# Bai 1
class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_message: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | extracted | queued | served

    # JSON gốc AI trả về, giữ nguyên để đối chiếu
    ai_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Dữ liệu hiện tại (AI điền, người dùng có thể sửa)
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    product: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(200), nullable=True)
    needs_human_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


# Bai 2
class Dock(Base):
    __tablename__ = "docks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    dock_type: Mapped[str] = mapped_column(String(20))  # standard | refrigerated

    bookings: Mapped[list["DockBooking"]] = relationship(back_populates="dock", order_by="DockBooking.start_at")


class DockRequest(Base):
    __tablename__ = "dock_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | extracted | booked
    ai_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    carrier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    earliest_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dock_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    missing_fields: Mapped[str | None] = mapped_column(String(200), nullable=True)  # cách nhau bởi dấu phẩy

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class DockBooking(Base):
    __tablename__ = "dock_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dock_id: Mapped[int] = mapped_column(ForeignKey("docks.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("dock_requests.id"), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    dock: Mapped["Dock"] = relationship(back_populates="bookings")


# Bai 3
class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | extracted | checked | reviewed
    ai_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # VND: đồng, USD: cent
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    missing_fields: Mapped[str | None] = mapped_column(String(200), nullable=True)

    check_status: Mapped[str | None] = mapped_column(String(40), nullable=True)  # duplicate_candidate | needs_review | unique_under_current_rules
    check_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: lý do, chứng từ trùng, chỗ khác nhau
    matched_expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)  # confirm_duplicate | dismiss_suspicion

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
