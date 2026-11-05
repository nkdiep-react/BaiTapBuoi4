import unicodedata

from app.model_db import Expense

SUPPORTED_CURRENCIES = {"VND", "USD"}
COMPARE_FIELDS = ["vendor", "invoice_number", "transaction_date", "amount_minor", "currency", "receipt_id"]


def normalize(value):
    # chuẩn hóa Unicode, bỏ dấu cách thừa, không phân biệt hoa thường; giữ nguyên dấu gạch nối
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    return value


def make_labels(expense: Expense) -> dict[tuple, str]:
    """Nhãn tra cứu -> tên nhãn. Có mã biên nhận thì dùng nó; có nơi bán + số hóa đơn thì thêm nhãn thứ hai."""
    labels = {}
    if normalize(expense.receipt_id):
        labels[("receipt", expense.currency, normalize(expense.receipt_id))] = "receipt"
    if normalize(expense.vendor) and normalize(expense.invoice_number):
        labels[("invoice", expense.currency, normalize(expense.vendor), normalize(expense.invoice_number))] = "invoice"
    return labels


def check_expense(expense: Expense, others: list[Expense]) -> dict:
    labels = make_labels(expense)

    problems = []
    if expense.currency not in SUPPORTED_CURRENCIES:
        problems.append(f"Loại tiền '{expense.currency}' không được hỗ trợ")
    if expense.amount_minor is None or expense.amount_minor <= 0:
        problems.append("Thiếu số tiền hoặc số tiền không lớn hơn 0")
    if expense.transaction_date is None:
        problems.append("Thiếu ngày giao dịch")
    if not labels:
        problems.append("Thiếu mã biên nhận, hoặc thiếu nơi bán/số hóa đơn nên không tạo được nhãn tra cứu")
    if problems:
        return {"status": "needs_review", "reasons": problems, "matched_expense_id": None, "matched_labels": [], "differences": []}

    # hash map: nhãn -> chứng từ đã có (giữ chứng từ đến trước)
    index = {}
    for other in others:
        for label in make_labels(other):
            index.setdefault(label, other)

    matches = [(name, index[label]) for label, name in labels.items() if label in index]
    if not matches:
        return {"status": "unique_under_current_rules", "reasons": [], "matched_expense_id": None, "matched_labels": [], "differences": []}

    matched = matches[0][1]
    differences = [
        {"field": field, "this": str(getattr(expense, field)), "matched": str(getattr(matched, field))}
        for field in COMPARE_FIELDS
        if normalize(getattr(expense, field)) != normalize(getattr(matched, field))
    ]
    return {
        "status": "duplicate_candidate",
        "reasons": [],
        "matched_expense_id": matched.id,
        "matched_labels": [name for name, _ in matches],
        "differences": differences,
    }
