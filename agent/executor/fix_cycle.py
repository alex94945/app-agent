from typing import Any, Dict, Optional, TypedDict, List

DEFAULT_MAX_FIX_ATTEMPTS_PER_TOOL = 3

class FailingToolRunDetails(TypedDict):
    name: str
    args: Dict[str, Any]
    id: str # Original tool_call_id of the failing tool
    output: Optional[str]

class FixCycleState(TypedDict):
    is_active: bool
    failing_tool_run: Optional[FailingToolRunDetails]
    fix_attempts_count: int # Number of patches/fixes attempted for this failing_tool_run
    max_attempts_for_cycle: int
    # True if a fix (e.g. patch) has been applied and the original tool needs to be re-run for verification.
    needs_verification: bool
    verification_history: List[bool] # True for success, False for fail

class FixCycleTracker:
    def __init__(self, state: Optional[FixCycleState] = None):
        if state:
            self._state: FixCycleState = state
        else:
            self._state: FixCycleState = FixCycleTracker._get_default_state()

    @staticmethod
    def _get_default_state() -> FixCycleState:
        return {
            "is_active": False,
            "failing_tool_run": None,
            "fix_attempts_count": 0,
            "max_attempts_for_cycle": DEFAULT_MAX_FIX_ATTEMPTS_PER_TOOL,
            "needs_verification": False,
            "verification_history": [],
        }

    @classmethod
    def from_state(cls, state_dict: Optional[Dict[str, Any]]) -> "FixCycleTracker":
        if not state_dict:
            return cls()  # __init__ will use _get_default_state

        default_state_values = FixCycleTracker._get_default_state()
        validated_state: FixCycleState = {
            "is_active": state_dict.get("is_active", default_state_values["is_active"]),
            "failing_tool_run": state_dict.get("failing_tool_run", default_state_values["failing_tool_run"]),
            "fix_attempts_count": state_dict.get("fix_attempts_count", default_state_values["fix_attempts_count"]),
            "max_attempts_for_cycle": state_dict.get("max_attempts_for_cycle", default_state_values["max_attempts_for_cycle"]),
            "needs_verification": state_dict.get("needs_verification", default_state_values["needs_verification"]),
            "verification_history": state_dict.get("verification_history", default_state_values["verification_history"]),
        }
        return cls(state=validated_state)

    def to_state(self) -> Dict[str, Any]:
        return self._state.copy()

    def start_fix_cycle(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str, 
        tool_output: Optional[str],
        max_attempts: Optional[int] = None,
    ) -> None:
        self._state["is_active"] = True
        self._state["failing_tool_run"] = {
            "name": tool_name,
            "args": tool_args,
            "id": tool_call_id,
            "output": tool_output,
        }
        self._state["fix_attempts_count"] = 0
        self._state["max_attempts_for_cycle"] = max_attempts or DEFAULT_MAX_FIX_ATTEMPTS_PER_TOOL
        self._state["needs_verification"] = False
        self._state["verification_history"] = []

    def record_tool_run(
        self,
        tool_name: str, 
        tool_args: Dict[str, Any],
        tool_call_id: str, 
        succeeded: bool,
        output_content: Optional[str],
        max_attempts_for_cycle: Optional[int] = None
    ) -> None:
        if not succeeded:
            self.start_fix_cycle(
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=tool_call_id,
                tool_output=output_content,
                max_attempts=max_attempts_for_cycle
            )

    def record_fix_attempt(self, fix_applied_successfully: bool) -> None:
        if not self._state["is_active"] or not self._state["failing_tool_run"]:
            return

        self._state["fix_attempts_count"] += 1
        if fix_applied_successfully:
            self._state["needs_verification"] = True
        else:
            self._state["needs_verification"] = False

    def get_tool_to_verify(self) -> Optional[FailingToolRunDetails]:
        if self._state["is_active"] and self._state["needs_verification"] and self._state["failing_tool_run"]:
            return self._state["failing_tool_run"]
        return None

    def record_verification_result(self, succeeded: bool) -> None:
        if not self._state["is_active"] or not self._state["needs_verification"] or not self._state["failing_tool_run"]:
            return

        self._state["verification_history"].append(succeeded)
        if succeeded:
            self._state.update(FixCycleTracker._get_default_state())
        else:
            self._state["needs_verification"] = False

    def needs_verification(self) -> bool:
        return self._state["is_active"] and self._state["needs_verification"]

    def has_reached_max_fix_attempts(self, global_max_attempts: Optional[int] = None) -> bool:
        if not self._state["is_active"]:
            return False
        limit = global_max_attempts if global_max_attempts is not None else self._state["max_attempts_for_cycle"]
        return self._state["fix_attempts_count"] >= limit

    def get_current_fix_state(self) -> Dict[str, Any]:
        return {
            "is_active": self._state["is_active"],
            "failing_tool_run_id": self._state["failing_tool_run"]["id"] if self._state["failing_tool_run"] else None,
            "failing_tool_name": self._state["failing_tool_run"]["name"] if self._state["failing_tool_run"] else None,
            "current_attempt_count": self._state["fix_attempts_count"],
            "max_attempts_for_cycle": self._state["max_attempts_for_cycle"],
            "needs_verification": self._state["needs_verification"],
            "verification_history_count": len(self._state["verification_history"]),
        }
