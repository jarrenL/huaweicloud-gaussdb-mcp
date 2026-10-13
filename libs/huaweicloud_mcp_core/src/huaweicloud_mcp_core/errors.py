"""LLM-readable error envelope and Huawei Cloud SDK error mapping."""

from typing import Any


class McpToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        request_id: str | None = None,
        doc_url: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code, self.message = code, message
        self.request_id, self.doc_url, self.hint = request_id, doc_url, hint

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.request_id:
            error["request_id"] = self.request_id
        if self.doc_url:
            error["doc_url"] = self.doc_url
        error["hint"] = self.hint or "Inspect the error message and adjust the tool call."
        return {"error": error}


def wrap_sdk_error(exc: Exception) -> McpToolError:
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "error_code", None) or (f"HTTP_{status}" if status else "MCP_SDK_ERROR")
    message = getattr(exc, "error_msg", None) or "Huawei Cloud API request failed."
    return McpToolError(
        code=str(code),
        message=str(message),
        request_id=getattr(exc, "request_id", None),
        hint="Check IAM permissions, resource state and request parameters, then retry. "
        "For asynchronous writes, query the job state before retrying.",
    )
