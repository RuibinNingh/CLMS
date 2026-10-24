class DomainError(Exception):
    def __init__(self, code, message, status=400, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)

    def payload(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def require(condition, code, message, status=400):
    if not condition:
        raise DomainError(code, message, status)
