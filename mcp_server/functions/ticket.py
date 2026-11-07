


# ticket.py
def get_ticket_id(department: str) -> str:
    """根据部门缩写生成工单号，格式为 TICKET-<部门大写>-4821。"""
    return f"TICKET-{department.upper()}-4821"


TOOLS = [get_ticket_id]



