from __future__ import annotations

from .models import MonitorResult, PolicyDecision, ToolCall


class PolicyEngine:
    def decide(self, monitor_result: MonitorResult, tool_call: ToolCall) -> PolicyDecision:
        action = monitor_result.recommended_action
        user_message = self._build_message(action, monitor_result, tool_call)

        return PolicyDecision(
            action=action,
            user_message=user_message,
            should_log=action in {"allow_with_logging", "block_and_log", "block_and_alert", "require_reauthentication"},
            should_alert=action == "block_and_alert",
        )

    @staticmethod
    def _build_message(action: str, monitor_result: MonitorResult, tool_call: ToolCall) -> str:
        if action == "allow":
            return "Request is within policy and may proceed."
        if action == "allow_with_logging":
            if tool_call.scope == "bulk":
                return "Request is unusual and will be logged. Only limited disclosure should proceed."
            return "Request may proceed, but the session has been flagged for review."
        if action == "require_reauthentication":
            return "This action requires additional authorization before protected data can be modified."
        if action == "block_and_log":
            return f"Request blocked due to {monitor_result.attack_type.replace('_', ' ')} indicators. The event has been logged."
        if action == "block_and_alert":
            return f"Request blocked due to high-risk {monitor_result.attack_type.replace('_', ' ')} behavior. Compliance review was triggered."
        return "Policy decision completed."
