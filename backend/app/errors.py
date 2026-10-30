class AppError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid(message: str):
    return AppError('INVALID_INPUT', message, 400)


def unsupported(message: str):
    return AppError('UNSUPPORTED_SGF', message, 422)


def invalid_result():
    return AppError('KATAGO_INVALID_RESULT', '引擎结果缺失或无法对应当前局面，请重试', 502)
