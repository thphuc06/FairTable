"""Names of the 8 MCP tools. Also used as Cedar action ids (``Action::"<name>"``)."""

from enum import StrEnum


class ToolName(StrEnum):
    RESTAURANT_SEARCH = "restaurant_search"
    AVAILABILITY_CHECK = "availability_check"
    MANDATE_STATUS = "mandate_status"
    RESERVATION_HOLD = "reservation_hold"
    RESERVATION_CONFIRM = "reservation_confirm"
    RESERVATION_MANAGE = "reservation_manage"
    WAITLIST_WATCH = "waitlist_watch"
    WAITLIST_STATUS = "waitlist_status"


READ_TOOLS = frozenset(
    {
        ToolName.RESTAURANT_SEARCH,
        ToolName.AVAILABILITY_CHECK,
        ToolName.MANDATE_STATUS,
        ToolName.WAITLIST_STATUS,
    }
)
WRITE_TOOLS = frozenset(
    {
        ToolName.RESERVATION_HOLD,
        ToolName.RESERVATION_CONFIRM,
        ToolName.RESERVATION_MANAGE,
        ToolName.WAITLIST_WATCH,
    }
)
