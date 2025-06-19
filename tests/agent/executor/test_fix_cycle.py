import pytest
from agent.executor.fix_cycle import FixCycleTracker, DEFAULT_MAX_FIX_ATTEMPTS_PER_TOOL, FixCycleState, FailingToolRunDetails

def test_default_initialization():
    tracker = FixCycleTracker()
    state = tracker.to_state()
    assert not state["is_active"]
    assert state["failing_tool_run"] is None
    assert state["fix_attempts_count"] == 0
    assert state["max_attempts_for_cycle"] == DEFAULT_MAX_FIX_ATTEMPTS_PER_TOOL
    assert not state["needs_verification"]
    assert state["verification_history"] == []
    assert not tracker.needs_verification()
    assert not tracker.has_reached_max_fix_attempts()
    assert tracker.get_tool_to_verify() is None

def test_start_fix_cycle_explicitly():
    tracker = FixCycleTracker()
    tool_name = "test_tool"
    tool_args = {"arg1": "val1"}
    tool_call_id = "call123"
    tool_output = "Error output"

    tracker.start_fix_cycle(tool_name, tool_args, tool_call_id, tool_output, max_attempts=2)
    state = tracker.to_state()

    assert state["is_active"]
    assert state["failing_tool_run"] == {
        "name": tool_name,
        "args": tool_args,
        "id": tool_call_id,
        "output": tool_output,
    }
    assert state["fix_attempts_count"] == 0
    assert state["max_attempts_for_cycle"] == 2
    assert not state["needs_verification"]
    assert not tracker.needs_verification()

def test_record_tool_run_failure_starts_cycle():
    tracker = FixCycleTracker()
    tool_name = "failed_tool"
    tool_args = {"param": "value"}
    tool_call_id = "call_fail_456"
    output_content = "Critical failure"

    tracker.record_tool_run(tool_name, tool_args, tool_call_id, succeeded=False, output_content=output_content)
    state = tracker.to_state()

    assert state["is_active"]
    assert state["failing_tool_run"]["name"] == tool_name
    assert state["failing_tool_run"]["args"] == tool_args
    assert state["failing_tool_run"]["id"] == tool_call_id
    assert state["failing_tool_run"]["output"] == output_content
    assert state["fix_attempts_count"] == 0
    assert state["max_attempts_for_cycle"] == DEFAULT_MAX_FIX_ATTEMPTS_PER_TOOL

def test_record_tool_run_success_does_not_start_cycle():
    tracker = FixCycleTracker()
    tracker.record_tool_run("succeeded_tool", {}, "call_succ_789", succeeded=True, output_content="Success")
    state = tracker.to_state()
    assert not state["is_active"]

def test_record_fix_attempt():
    tracker = FixCycleTracker()
    tracker.start_fix_cycle("tool_a", {}, "id_a", "err_a")

    tracker.record_fix_attempt(fix_applied_successfully=True)
    state = tracker.to_state()
    assert state["fix_attempts_count"] == 1
    assert state["needs_verification"]
    assert tracker.needs_verification()

    tracker.record_fix_attempt(fix_applied_successfully=False) # e.g. patch failed to apply
    state = tracker.to_state()
    assert state["fix_attempts_count"] == 2
    assert not state["needs_verification"]
    assert not tracker.needs_verification()

def test_get_tool_to_verify():
    tracker = FixCycleTracker()
    assert tracker.get_tool_to_verify() is None

    tracker.start_fix_cycle("tool_b", {"b_arg": 1}, "id_b", "err_b")
    assert tracker.get_tool_to_verify() is None # Not yet needing verification

    tracker.record_fix_attempt(fix_applied_successfully=True)
    failing_run_details = tracker.get_tool_to_verify()
    assert failing_run_details is not None
    assert failing_run_details["name"] == "tool_b"
    assert failing_run_details["id"] == "id_b"

    tracker.record_verification_result(succeeded=True) # Cycle ends
    assert tracker.get_tool_to_verify() is None

def test_record_verification_result():
    tracker = FixCycleTracker()
    tracker.start_fix_cycle("tool_c", {}, "id_c", "err_c")
    tracker.record_fix_attempt(fix_applied_successfully=True)

    # Successful verification
    tracker.record_verification_result(succeeded=True)
    state = tracker.to_state()
    assert not state["is_active"] # Cycle should reset
    assert state["verification_history"] == [] # History is reset with the state on successful verification
    assert not tracker.needs_verification()

    # Failed verification
    tracker.start_fix_cycle("tool_d", {}, "id_d", "err_d")
    tracker.record_fix_attempt(fix_applied_successfully=True)
    tracker.record_verification_result(succeeded=False)
    state = tracker.to_state()
    assert state["is_active"] # Cycle continues
    assert not state["needs_verification"] # But tool doesn't need re-run immediately
    assert state["verification_history"] == [False]
    assert state["fix_attempts_count"] == 1 # Fix attempts not reset by failed verification

def test_has_reached_max_fix_attempts():
    tracker = FixCycleTracker()
    tracker.start_fix_cycle("tool_e", {}, "id_e", "err_e", max_attempts=2)
    assert tracker.to_state()["max_attempts_for_cycle"] == 2 # Verify max_attempts is set correctly

    assert not tracker.has_reached_max_fix_attempts()
    tracker.record_fix_attempt(True)
    assert not tracker.has_reached_max_fix_attempts()
    tracker.record_fix_attempt(True)
    assert tracker.has_reached_max_fix_attempts()

    # Test with global override
    assert not tracker.has_reached_max_fix_attempts(global_max_attempts=3) # 2 attempts is not >= 3
    tracker.record_fix_attempt(True)
    assert tracker.has_reached_max_fix_attempts(global_max_attempts=3)

def test_state_serialization_deserialization():
    tracker1 = FixCycleTracker()
    tracker1.start_fix_cycle("tool_f", {"f_arg": "foo"}, "id_f", "err_f", max_attempts=5)
    tracker1.record_fix_attempt(True)
    tracker1.record_verification_result(False)
    tracker1.record_fix_attempt(False)

    state_dict = tracker1.to_state()

    tracker2 = FixCycleTracker.from_state(state_dict)
    assert tracker2.to_state() == state_dict

    # Test from_state with None
    tracker3 = FixCycleTracker.from_state(None)
    default_state = FixCycleTracker()._get_default_state()
    assert tracker3.to_state() == default_state

def test_get_current_fix_state_summary():
    tracker = FixCycleTracker()
    summary_initial = tracker.get_current_fix_state()
    assert not summary_initial["is_active"]
    assert summary_initial["failing_tool_run_id"] is None

    tracker.start_fix_cycle("tool_g", {"g_arg": 123}, "id_g123", "err_g", max_attempts=4)
    tracker.record_fix_attempt(True)

    summary_active = tracker.get_current_fix_state()
    assert summary_active["is_active"]
    assert summary_active["failing_tool_run_id"] == "id_g123"
    assert summary_active["failing_tool_name"] == "tool_g"
    assert summary_active["current_attempt_count"] == 1
    assert summary_active["max_attempts_for_cycle"] == 4
    assert summary_active["needs_verification"]
    assert summary_active["verification_history_count"] == 0

    tracker.record_verification_result(False)
    summary_after_failed_verify = tracker.get_current_fix_state()
    assert summary_after_failed_verify["is_active"]
    assert not summary_after_failed_verify["needs_verification"]
    assert summary_after_failed_verify["verification_history_count"] == 1

    tracker.record_verification_result(True) # This would be after another fix attempt + verification
    # To test this properly, we need to simulate the full flow:
    tracker.start_fix_cycle("tool_h", {}, "id_h", "err_h")
    tracker.record_fix_attempt(True)
    tracker.record_verification_result(True) # Successful verification resets
    summary_after_success_verify = tracker.get_current_fix_state()
    assert not summary_after_success_verify["is_active"]
