from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import date, datetime
import json
from typing import Literal

def _require_non_empty(value: str, field_name: str) -> str:
    """Strip whitespace and reject empty values."""
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    return value


class RegisterIn(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("username")
    @classmethod
    def nonempty_username(cls, v: str) -> str:
        return _require_non_empty(v, "Username")

    @field_validator("email")
    @classmethod
    def nonempty_email(cls, v: str) -> str:
        return _require_non_empty(v, "Email")

    @field_validator("password")
    @classmethod
    def nonempty_password(cls, v: str) -> str:
        return _require_non_empty(v, "Password")

# Bai 1 Ticket
Intent = Literal["billing", "technical", "account", "other"]
Severity = Literal["low", "medium", "high", "critical"]


# Mẫu JSON AI phải điền (Structured Output)
class TicketExtraction(BaseModel):
    ticket_id: str = Field(description="Mã ticket hệ thống đã cấp, chép lại đúng")
    intent: Intent = Field(description="billing: thanh toán, technical: lỗi kỹ thuật, account: tài khoản, other: việc khác")
    severity: Severity = Field(description="Mức độ khẩn cấp của khách")
    product: str | None = Field(default=None, description="Tên sản phẩm khách nhắc tới, null nếu không nói")
    summary: str = Field(max_length=200, description="Tóm tắt ngắn")
    needs_human_review: bool = Field(description="true nếu tin nhắn mơ hồ")


class TicketCreateIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    received_at: datetime | None = None  # ISO 8601 có múi giờ, bỏ trống = bây giờ

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, v: str) -> str:
        return _require_non_empty(v, "Message")

    @field_validator("received_at")
    @classmethod
    def received_at_has_timezone(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("received_at phải có múi giờ, ví dụ 2026-10-21T09:00:00+07:00")
        return v


class TicketExtractIn(BaseModel):
    ticket_id: int


# Dữ liệu người dùng đã xem/sửa
class TicketConfirmIn(BaseModel):
    ticket_id: int
    intent: Intent
    severity: Severity
    product: str | None = None
    summary: str = Field(min_length=1, max_length=200)
    needs_human_review: bool = False


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_message: str
    received_at: datetime  
    status: str
    intent: str | None
    severity: str | None
    product: str | None
    summary: str | None
    needs_human_review: bool | None
    deadline_at: datetime | None  


class QueueItemOut(BaseModel):
    position: int
    reason: str
    ticket: TicketOut


class QueueOut(BaseModel):
    size: int
    items: list[QueueItemOut]


def _require_timezone(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("Thời gian phải có múi giờ, ví dụ 2026-10-21T09:00:00+07:00")
    return v


# Bai 2 Dock
DockType = Literal["standard", "refrigerated"]


# Mẫu JSON AI phải điền từ email của nhà vận chuyển (Structured Output)
class DockRequestExtraction(BaseModel):
    request_id: str = Field(description="Mã yêu cầu hệ thống đã cấp, chép lại đúng")
    carrier: str | None = Field(default=None, description="Tên nhà vận chuyển")
    earliest_start: str | None = Field(default=None, description="Giờ sớm nhất xe có thể đến, ISO 8601 có múi giờ, vd 2026-10-21T09:00:00+07:00")
    duration_minutes: int | None = Field(default=None, description="Số phút cần dùng ca kho. null nếu email không nói, không tự đoán")
    dock_type: DockType = Field(description="standard: ca thường, refrigerated: ca lạnh (hàng cần giữ lạnh)")
    missing_fields: list[str] = Field(description="Tên các trường email không nói, ví dụ ['duration_minutes']")


class DockRequestCreateIn(BaseModel):
    email_text: str = Field(min_length=1, max_length=5000)


class DockRequestExtractIn(BaseModel):
    request_id: int


class DockRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_text: str
    status: str
    carrier: str | None
    earliest_start: datetime | None  
    duration_minutes: int | None
    dock_type: str | None
    missing_fields: str | None


class DockRequestExtractOut(BaseModel):
    request: DockRequestOut
    errors: list[str]


class SlotSuggestIn(BaseModel):
    request_id: int
    earliest_start: datetime
    duration_minutes: int = Field(gt=0)
    dock_type: DockType

    @field_validator("earliest_start")
    @classmethod
    def earliest_start_has_timezone(cls, v: datetime) -> datetime:
        return _require_timezone(v)


class SlotSuggestOut(BaseModel):
    status: Literal["ok", "no_slot"]
    dock_code: str | None = None
    start_at: datetime | None = None  
    end_at: datetime | None = None  


class BookingConfirmIn(BaseModel):
    request_id: int
    dock_code: str
    start_at: datetime

    @field_validator("start_at")
    @classmethod
    def start_at_has_timezone(cls, v: datetime) -> datetime:
        return _require_timezone(v)


class DockCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    dock_type: DockType


class ExistingBookingIn(BaseModel):
    dock_code: str
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def time_has_timezone(cls, v: datetime) -> datetime:
        return _require_timezone(v)

    @field_validator("end_at")
    @classmethod
    def end_after_start(cls, v: datetime, info) -> datetime:
        start = info.data.get("start_at")
        if start is not None and v <= start:
            raise ValueError("end_at phải sau start_at")
        return v


class BookingOut(BaseModel):
    id: int
    dock_code: str
    request_id: int | None
    start_at: datetime  
    end_at: datetime  


class DockBookingItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int | None
    start_at: datetime
    end_at: datetime


class DockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    dock_type: str
    bookings: list[DockBookingItem]


# Bai 3 Expense
# Mẫu JSON AI phải điền từ văn bản chứng từ (Structured Output)
class ExpenseExtraction(BaseModel):
    submission_id: str = Field(description="Mã bản gửi hệ thống đã cấp, chép lại đúng")
    vendor: str | None = Field(default=None, description="Tên nơi bán")
    invoice_number: str | None = Field(default=None, description="Số hóa đơn, giữ nguyên dấu gạch nối")
    transaction_date: str | None = Field(default=None, description="Ngày giao dịch, định dạng YYYY-MM-DD")
    amount_minor: int | None = Field(default=None, description="Số tiền theo đơn vị nhỏ nhất, số nguyên (VND: đồng, USD: cent)")
    currency: str | None = Field(default=None, description="Mã tiền tệ như VND, USD")
    receipt_id: str | None = Field(default=None, description="Mã biên nhận")
    missing_fields: list[str] = Field(description="Tên các trường chứng từ không có, các trường đó để null")


class ExpenseCreateIn(BaseModel):
    raw_text: str = Field(min_length=1, max_length=5000)


class ExpenseExtractIn(BaseModel):
    expense_id: int


# Dữ liệu người dùng đã xem/sửa rồi gửi đi kiểm tra trùng
class ExpenseCheckIn(BaseModel):
    expense_id: int
    vendor: str | None = None
    invoice_number: str | None = None
    transaction_date: date | None = None
    amount_minor: int | None = None
    currency: str | None = None
    receipt_id: str | None = None


class ExpenseReviewIn(BaseModel):
    expense_id: int
    decision: Literal["confirm_duplicate", "dismiss_suspicion"]


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_text: str
    status: str
    vendor: str | None
    invoice_number: str | None
    transaction_date: date | None
    amount_minor: int | None
    currency: str | None
    receipt_id: str | None
    missing_fields: str | None
    check_status: str | None
    check_detail: dict | None
    matched_expense_id: int | None
    review_decision: str | None

    @field_validator("check_detail", mode="before")
    @classmethod
    def parse_check_detail(cls, v):
        return json.loads(v) if isinstance(v, str) else v


class ExpenseExtractOut(BaseModel):
    expense: ExpenseOut
    errors: list[str]
