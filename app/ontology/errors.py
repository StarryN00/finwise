from __future__ import annotations


class DomainError(Exception):
    """Expected business or authorization error."""

    def __init__(self, message: str, code: str = "DOMAIN_ERROR", status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class ScopeViolation(DomainError):
    def __init__(self, message: str = "对象 Scope 不匹配"):
        super().__init__(message, "SCOPE_VIOLATION", 403)


class VersionConflict(DomainError):
    def __init__(self, message: str = "对象版本冲突，请刷新后重试"):
        super().__init__(message, "VERSION_CONFLICT", 409)


class PreconditionFailed(DomainError):
    def __init__(self, message: str):
        super().__init__(message, "PRECONDITION_FAILED", 409)


class PermissionDenied(DomainError):
    def __init__(self, message: str = "当前角色没有执行该动作的权限"):
        super().__init__(message, "PERMISSION_DENIED", 403)


class GatewayPaused(DomainError):
    def __init__(self, message: str, gateway_code: str = "GATEWAY_PAUSED"):
        super().__init__(message, "GATEWAY_PAUSED", 422)
        self.gateway_code = gateway_code


class RuleConflictDetected(PreconditionFailed):
    def __init__(self, candidate, conflict_data):
        super().__init__("本期事实与历史规则冲突，需处理冲突后再确认")
        self.candidate = candidate
        self.conflict_data = conflict_data
