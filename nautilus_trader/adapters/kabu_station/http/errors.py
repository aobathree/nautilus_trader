class KabuStationApiError(Exception):
    """
    kabusapi error: HTTP 4xx/5xx, or HTTP 200 with ``Result != 0``.

    エラーコード表は再実装せず、API の Message をそのまま伝搬する。
    """

    def __init__(self, code: int, message: str, http_status: int = 200) -> None:
        super().__init__(f"kabusapi error {code} (HTTP {http_status}): {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
