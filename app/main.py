import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base
from .database import make_session_factory
from . import model_db  # noqa: F401  (import registers the models on Base.metadata)
from .config import Settings
from .dependencies import get_db
from .model_db import User, Ticket, Dock, DockRequest, DockBooking, Expense
from .schemas import (
    RegisterIn, TicketCreateIn, TicketExtractIn, TicketConfirmIn,
    TicketOut, QueueItemOut, QueueOut,
    DockRequestCreateIn, DockRequestExtractIn, DockRequestOut, DockRequestExtractOut,
    SlotSuggestIn, SlotSuggestOut, BookingConfirmIn, BookingOut,
    DockCreateIn, DockOut, ExistingBookingIn,
    ExpenseCreateIn, ExpenseExtractIn, ExpenseCheckIn, ExpenseReviewIn, ExpenseOut, ExpenseExtractOut,
)
from .security import hash_password
from .services.extractor import read_message_openai, read_dock_email_openai, read_expense_openai, AIError
from .services.ticket_queue import TicketQueue, calculate_deadline, explain_rank
from .services.dock_slots import suggest_slot, has_conflict, working_window
from .services.expense_check import check_expense


def to_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_open_ticket(db: Session, ticket_id: int) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ticket")
    if ticket.status in ("queued", "served"):
        raise HTTPException(status_code=400, detail="Ticket đã vào hàng đợi, không sửa được nữa")
    return ticket


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(app.state.engine)
    # Dựng lại hàng đợi từ các ticket đã xác nhận nhưng chưa xử lý
    with app.state.sessionfactory() as db:
        for ticket in db.scalars(select(Ticket).where(Ticket.status == "queued")):
            app.state.queue.add(ticket)
    yield
    app.state.engine.dispose()


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    engine, sessionfactory = make_session_factory(settings.DATABASE_URL)
    app.state.engine = engine
    app.state.sessionfactory = sessionfactory
    app.state.settings = settings
    app.state.queue = TicketQueue()

    @app.get("/", include_in_schema=False)
    async def home_page():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/api/health")
    async def health_check():
        return {"status": "healthy"}

    @app.post("/api/register")
    async def register_user(register_data: RegisterIn, db: Session = Depends(get_db)):
        user = User(username=register_data.username, email=register_data.email, password=hash_password(register_data.password))
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=403, detail="User with this email already exists")
        db.refresh(user)
        return {"message": "User registered successfully", "user": user}

#Bai 1
    # insert new ticket 
    @app.post("/api/tickets", response_model=TicketOut)
    async def create_ticket(payload: TicketCreateIn, db: Session = Depends(get_db)):
        received_at = payload.received_at or datetime.now(timezone.utc)
        ticket = Ticket(raw_message=payload.message, received_at=to_utc_naive(received_at))
        db.add(ticket)
        db.commit()
        return ticket

    # AI to extract ticket
    @app.post("/api/tickets/extract", response_model=TicketOut)
    async def extract_ticket(payload: TicketExtractIn, db: Session = Depends(get_db)):
        ticket = get_open_ticket(db, payload.ticket_id)

        try:
            data = read_message_openai(ticket.id, ticket.raw_message, app.state.settings)
        except AIError as exc:
            ticket.needs_human_review = True
            db.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        ticket.ai_json = data.model_dump_json()
        ticket.intent = data.intent
        ticket.severity = data.severity
        ticket.product = data.product
        ticket.summary = data.summary
        ticket.needs_human_review = data.needs_human_review
        ticket.deadline_at = calculate_deadline(ticket.received_at, data.severity)
        ticket.status = "extracted"
        db.commit()
        return ticket

    # Confirm ticket after user review
    @app.post("/api/tickets/confirm", response_model=TicketOut)
    async def confirm_ticket(payload: TicketConfirmIn, db: Session = Depends(get_db)):
        ticket = get_open_ticket(db, payload.ticket_id)
        if ticket.status != "extracted":
            raise HTTPException(status_code=400, detail="Ticket chưa được extract")

        ticket.intent = payload.intent
        ticket.severity = payload.severity
        ticket.product = (payload.product or "").strip() or None
        ticket.summary = payload.summary.strip()
        ticket.needs_human_review = payload.needs_human_review
        ticket.deadline_at = calculate_deadline(ticket.received_at, payload.severity)
        ticket.status = "queued"
        db.commit()
        app.state.queue.add(ticket)
        return ticket

    @app.get("/api/tickets/queue", response_model=QueueOut)
    async def get_queue(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
        tickets = [db.get(Ticket, ticket_id) for ticket_id in app.state.queue.top_k(limit)]
        items = [
            QueueItemOut(
                position=index + 1,
                reason=explain_rank(ticket, tickets[index - 1] if index > 0 else None),
                ticket=ticket,
            )
            for index, ticket in enumerate(tickets)
        ]
        return QueueOut(size=len(app.state.queue), items=items)

    @app.post("/api/tickets/next", response_model=TicketOut)
    async def next_ticket(db: Session = Depends(get_db)):
        ticket_id = app.state.queue.pop()
        if ticket_id is None:
            raise HTTPException(status_code=404, detail="Hàng đợi đang trống")
        ticket = db.get(Ticket, ticket_id)
        ticket.status = "served"
        db.commit()
        return ticket

# Bai 2
    # insert dock
    @app.post("/api/docks", response_model=DockOut)
    async def create_dock(payload: DockCreateIn, db: Session = Depends(get_db)):
        if db.scalar(select(Dock).where(Dock.code == payload.code)):
            raise HTTPException(status_code=400, detail="Mã ca đã tồn tại")
        dock = Dock(code=payload.code, dock_type=payload.dock_type)
        db.add(dock)
        db.commit()
        return dock

    # schedule of every dock
    @app.get("/api/docks", response_model=list[DockOut])
    async def list_docks(db: Session = Depends(get_db)):
        return db.scalars(select(Dock).order_by(Dock.code)).all()

    # insert an existing booking (not from AI)
    @app.post("/api/bookings", response_model=BookingOut)
    async def create_existing_booking(payload: ExistingBookingIn, db: Session = Depends(get_db)):
        dock = db.scalar(select(Dock).where(Dock.code == payload.dock_code))
        if dock is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy ca")
        start = to_utc_naive(payload.start_at)
        end = to_utc_naive(payload.end_at)
        if has_conflict([(b.start_at, b.end_at) for b in dock.bookings], start, end):
            raise HTTPException(status_code=409, detail="Trùng với lịch đã có")
        booking = DockBooking(dock_id=dock.id, start_at=start, end_at=end)
        db.add(booking)
        db.commit()
        return BookingOut(id=booking.id, dock_code=dock.code, request_id=None, start_at=start, end_at=end)

    # insert new request (email)
    @app.post("/api/requests", response_model=DockRequestOut)
    async def create_dock_request(payload: DockRequestCreateIn, db: Session = Depends(get_db)):
        dock_request = DockRequest(email_text=payload.email_text)
        db.add(dock_request)
        db.commit()
        return dock_request

    # AI reads the email and saves into the same request
    @app.post("/api/requests/extract", response_model=DockRequestExtractOut)
    async def extract_dock_request(payload: DockRequestExtractIn, db: Session = Depends(get_db)):
        dock_request = db.get(DockRequest, payload.request_id)
        if dock_request is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
        if dock_request.status == "booked":
            raise HTTPException(status_code=400, detail="Yêu cầu đã được đặt ca")

        try:
            data = read_dock_email_openai(dock_request.id, dock_request.email_text, app.state.settings)
        except AIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        errors = []
        dock_request.earliest_start = None
        if data.earliest_start:
            try:
                parsed = datetime.fromisoformat(data.earliest_start)
                if parsed.tzinfo is None:
                    errors.append("earliest_start AI trả về thiếu múi giờ, cần nhập lại")
                else:
                    dock_request.earliest_start = to_utc_naive(parsed)
            except ValueError:
                errors.append(f"earliest_start '{data.earliest_start}' không đúng định dạng ISO 8601")
        else:
            errors.append("Thiếu giờ xe có thể đến (earliest_start)")

        if data.duration_minutes is None:
            errors.append("Email không nói cần bao lâu (duration_minutes), cần hỏi lại người đặt")
            dock_request.duration_minutes = None
        elif data.duration_minutes <= 0:
            errors.append("duration_minutes phải lớn hơn 0")
            dock_request.duration_minutes = None
        else:
            dock_request.duration_minutes = data.duration_minutes

        dock_request.ai_json = data.model_dump_json()
        dock_request.carrier = data.carrier
        dock_request.dock_type = data.dock_type
        dock_request.missing_fields = ",".join(data.missing_fields) or None
        dock_request.status = "extracted"
        db.commit()
        return DockRequestExtractOut(request=dock_request, errors=errors)

    # find the earliest free slot (user may have edited the extracted data)
    @app.post("/api/slots/suggest", response_model=SlotSuggestOut)
    async def suggest_dock_slot(payload: SlotSuggestIn, db: Session = Depends(get_db)):
        dock_request = db.get(DockRequest, payload.request_id)
        if dock_request is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
        if dock_request.status != "extracted":
            raise HTTPException(status_code=400, detail="Yêu cầu chưa extract hoặc đã được đặt ca")

        earliest = to_utc_naive(payload.earliest_start)
        dock_request.earliest_start = earliest
        dock_request.duration_minutes = payload.duration_minutes
        dock_request.dock_type = payload.dock_type
        db.commit()

        docks = db.scalars(select(Dock).where(Dock.dock_type == payload.dock_type)).all()
        busy = {dock.code: [(b.start_at, b.end_at) for b in dock.bookings] for dock in docks}
        slot = suggest_slot(busy, earliest, payload.duration_minutes)
        if slot is None:
            return SlotSuggestOut(status="no_slot")
        code, start = slot
        return SlotSuggestOut(
            status="ok", dock_code=code, start_at=start,
            end_at=start + timedelta(minutes=payload.duration_minutes),
        )

    # book the slot, re-checking the latest schedule first
    @app.post("/api/bookings/confirm", response_model=BookingOut)
    async def confirm_booking(payload: BookingConfirmIn, db: Session = Depends(get_db)):
        dock_request = db.get(DockRequest, payload.request_id)
        if dock_request is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
        if dock_request.status != "extracted" or dock_request.duration_minutes is None:
            raise HTTPException(status_code=400, detail="Yêu cầu chưa đủ thông tin hoặc đã được đặt ca")
        dock = db.scalar(select(Dock).where(Dock.code == payload.dock_code))
        if dock is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy ca")
        if dock.dock_type != dock_request.dock_type:
            raise HTTPException(status_code=400, detail="Loại ca không đúng với yêu cầu")

        start = to_utc_naive(payload.start_at)
        end = start + timedelta(minutes=dock_request.duration_minutes)
        open_time, close_time = working_window(start)
        if start < open_time or end > close_time:
            raise HTTPException(status_code=400, detail="Ngoài giờ làm việc của kho (08:00-18:00)")
        if has_conflict([(b.start_at, b.end_at) for b in dock.bookings], start, end):
            raise HTTPException(status_code=409, detail="Khung giờ này vừa có người đặt, hãy gợi ý lại")

        booking = DockBooking(dock_id=dock.id, request_id=dock_request.id, start_at=start, end_at=end)
        dock_request.status = "booked"
        db.add(booking)
        db.commit()
        return BookingOut(id=booking.id, dock_code=dock.code, request_id=dock_request.id, start_at=start, end_at=end)

# Bai 3
    # insert new expense (document text)
    @app.post("/api/expenses", response_model=ExpenseOut)
    async def create_expense(payload: ExpenseCreateIn, db: Session = Depends(get_db)):
        expense = Expense(raw_text=payload.raw_text)
        db.add(expense)
        db.commit()
        return expense

    # AI reads the document and saves into the same expense
    @app.post("/api/expenses/extract", response_model=ExpenseExtractOut)
    async def extract_expense(payload: ExpenseExtractIn, db: Session = Depends(get_db)):
        expense = db.get(Expense, payload.expense_id)
        if expense is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy chứng từ")
        if expense.status == "reviewed":
            raise HTTPException(status_code=400, detail="Chứng từ đã được duyệt")

        try:
            data = read_expense_openai(expense.id, expense.raw_text, app.state.settings)
        except AIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        errors = []
        expense.transaction_date = None
        if data.transaction_date:
            try:
                expense.transaction_date = datetime.strptime(data.transaction_date, "%Y-%m-%d").date()
            except ValueError:
                errors.append(f"transaction_date '{data.transaction_date}' không đúng định dạng YYYY-MM-DD")

        expense.ai_json = data.model_dump_json()
        expense.vendor = data.vendor
        expense.invoice_number = data.invoice_number
        expense.amount_minor = data.amount_minor
        expense.currency = (data.currency or "").strip().upper() or None
        expense.receipt_id = data.receipt_id
        expense.missing_fields = ",".join(data.missing_fields) or None
        expense.status = "extracted"
        expense.check_status = None
        expense.check_detail = None
        expense.matched_expense_id = None
        db.commit()
        return ExpenseExtractOut(expense=expense, errors=errors)

    # check duplicates with the (possibly edited) data; run again after every edit
    @app.post("/api/expenses/check", response_model=ExpenseOut)
    async def check_expense_duplicate(payload: ExpenseCheckIn, db: Session = Depends(get_db)):
        expense = db.get(Expense, payload.expense_id)
        if expense is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy chứng từ")
        if expense.status == "new":
            raise HTTPException(status_code=400, detail="Chứng từ chưa extract")
        if expense.status == "reviewed":
            raise HTTPException(status_code=400, detail="Chứng từ đã được duyệt")

        expense.vendor = (payload.vendor or "").strip() or None
        expense.invoice_number = (payload.invoice_number or "").strip() or None
        expense.transaction_date = payload.transaction_date
        expense.amount_minor = payload.amount_minor
        expense.currency = (payload.currency or "").strip().upper() or None
        expense.receipt_id = (payload.receipt_id or "").strip() or None

        others = db.scalars(
            select(Expense).where(Expense.id != expense.id, Expense.status.in_(["checked", "reviewed"])).order_by(Expense.id)
        ).all()
        result = check_expense(expense, others)

        expense.check_status = result["status"]
        expense.check_detail = json.dumps(result, ensure_ascii=False)
        expense.matched_expense_id = result["matched_expense_id"]
        expense.status = "checked"
        db.commit()
        return expense

    # reviewer confirms the duplicate or dismisses the suspicion
    @app.post("/api/expenses/review", response_model=ExpenseOut)
    async def review_expense(payload: ExpenseReviewIn, db: Session = Depends(get_db)):
        expense = db.get(Expense, payload.expense_id)
        if expense is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy chứng từ")
        if expense.status != "checked":
            raise HTTPException(status_code=400, detail="Chứng từ chưa được kiểm tra trùng hoặc đã duyệt rồi")
        expense.review_decision = payload.decision
        expense.status = "reviewed"
        db.commit()
        return expense

    return app


app = create_app(Settings())
