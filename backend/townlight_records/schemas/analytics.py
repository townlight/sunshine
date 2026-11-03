from pydantic import BaseModel


class OperationalMetrics(BaseModel):
    average_response_time_days: float | None
    median_response_time_days: float | None
    requests_by_status: dict[str, int]
    requests_by_department: dict[str, int]
    deadline_compliance_rate: float
    total_open: int
    total_closed: int
    total_overdue: int
    clarification_frequency: float
    top_request_topics: list[str]
