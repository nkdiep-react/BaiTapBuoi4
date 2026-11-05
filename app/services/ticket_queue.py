import heapq
from datetime import datetime, timedelta

from app.model_db import Ticket

SLA_MINUTES = {"critical": 30, "high": 120, "medium": 480, "low": 1440}
SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def calculate_deadline(received_at: datetime, severity: str) -> datetime:
    return received_at + timedelta(minutes=SLA_MINUTES[severity])


def priority_key(ticket: Ticket) -> tuple:
    # heap lấy giá trị nhỏ nhất trước nên severity đặt dấu trừ
    return (ticket.deadline_at, -SEVERITY_RANK[ticket.severity], ticket.received_at, str(ticket.id))


class TicketQueue:
    def __init__(self):
        self.heap = []
        self.ids = set()

    def __len__(self):
        return len(self.heap)

    def add(self, ticket: Ticket) -> bool:
        if ticket.id in self.ids:
            return False
        heapq.heappush(self.heap, (priority_key(ticket), ticket.id))
        self.ids.add(ticket.id)
        return True

    def top_k(self, k: int) -> list[int]:
        # chỉ xem, không lấy ticket ra khỏi heap
        return [ticket_id for _, ticket_id in heapq.nsmallest(k, self.heap)]

    def pop(self) -> int | None:
        if not self.heap:
            return None
        _, ticket_id = heapq.heappop(self.heap)
        self.ids.discard(ticket_id)
        return ticket_id


def explain_rank(ticket: Ticket, previous: Ticket | None) -> str:
    if previous is None:
        return "Đứng đầu vì hạn xử lý sớm nhất"
    if ticket.deadline_at > previous.deadline_at:
        return f"Hạn xử lý muộn hơn ticket {previous.id}"
    if SEVERITY_RANK[ticket.severity] < SEVERITY_RANK[previous.severity]:
        return f"Cùng hạn với ticket {previous.id} nhưng mức khẩn cấp thấp hơn"
    if ticket.received_at > previous.received_at:
        return f"Cùng hạn và mức khẩn cấp với ticket {previous.id} nhưng nhận sau"
    return f"Giống hệt ticket {previous.id}, xếp theo mã"
