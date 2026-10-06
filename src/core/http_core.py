"""Микро-фреймворк для REST API на базе :mod:`http.server`.

Реализует маршрутизацию с параметрами пути, разбор JSON-тела запроса,
единообразную обработку ошибок и передачу управления обработчикам модулей.
"""

from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .config import settings
from .errors import ProjectFlowError

#: Тип обработчика: функция, принимающая запрос и возвращающая ответ.
Handler = Callable[["Request"], "Response"]


@dataclass
class Request:
    """Разобранный HTTP-запрос."""

    method: str
    path: str
    path_params: dict[str, str] = field(default_factory=dict)
    query: dict[str, list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    raw_body: bytes = b""
    user: dict[str, Any] | None = None

    def query_one(self, name: str, default: str | None = None) -> str | None:
        """Вернуть первое значение параметра строки запроса."""
        values = self.query.get(name)
        return values[0] if values else default

    def query_int(self, name: str, default: int | None = None) -> int | None:
        """Вернуть целочисленный параметр строки запроса."""
        raw = self.query_one(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ProjectFlowError(f"Параметр '{name}' должен быть целым числом", 400) from exc

    def bearer_token(self) -> str | None:
        """Извлечь токен из заголовка ``Authorization: Bearer <token>``."""
        header = self.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        return header[7:].strip() or None


@dataclass
class Response:
    """HTTP-ответ."""

    status: int = 200
    payload: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None
    content_type: str = "application/json; charset=utf-8"

    @classmethod
    def json(cls, payload: Any, status: int = 200) -> "Response":
        """Создать JSON-ответ."""
        return cls(status=status, payload=payload)

    @classmethod
    def created(cls, payload: Any) -> "Response":
        """Создать ответ 201 Created."""
        return cls(status=201, payload=payload)

    @classmethod
    def no_content(cls) -> "Response":
        """Создать ответ 204 No Content."""
        return cls(status=204, payload=None)

    @classmethod
    def binary(cls, data: bytes, content_type: str,
               filename: str | None = None) -> "Response":
        """Создать ответ с бинарным содержимым (файлом)."""
        headers: dict[str, str] = {}
        if filename:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return cls(status=200, raw=data, content_type=content_type, headers=headers)


class Router:
    """Реестр маршрутов с поддержкой параметров вида ``{id}``."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        """Зарегистрировать обработчик для метода и шаблона пути."""
        regex = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r"(?P<\1>[^/]+)", pattern)
        self._routes.append((method.upper(), re.compile(f"^{regex}$"), handler))

    def route(self, method: str, pattern: str) -> Callable[[Handler], Handler]:
        """Декоратор для регистрации обработчика."""
        def decorator(handler: Handler) -> Handler:
            self.add(method, pattern, handler)
            return handler
        return decorator

    def get(self, pattern: str) -> Callable[[Handler], Handler]:
        """Декоратор для GET-маршрута."""
        return self.route("GET", pattern)

    def post(self, pattern: str) -> Callable[[Handler], Handler]:
        """Декоратор для POST-маршрута."""
        return self.route("POST", pattern)

    def put(self, pattern: str) -> Callable[[Handler], Handler]:
        """Декоратор для PUT-маршрута."""
        return self.route("PUT", pattern)

    def patch(self, pattern: str) -> Callable[[Handler], Handler]:
        """Декоратор для PATCH-маршрута."""
        return self.route("PATCH", pattern)

    def delete(self, pattern: str) -> Callable[[Handler], Handler]:
        """Декоратор для DELETE-маршрута."""
        return self.route("DELETE", pattern)

    def resolve(self, method: str, path: str) -> tuple[Handler | None, dict[str, str]]:
        """Найти обработчик и извлечь параметры пути.

        :return: пара (обработчик или ``None``, словарь параметров)
        """
        method = method.upper()
        for route_method, regex, handler in self._routes:
            if route_method != method:
                continue
            match = regex.match(path)
            if match:
                return handler, match.groupdict()
        return None, {}

    def has_path(self, path: str) -> bool:
        """Проверить, зарегистрирован ли путь хотя бы для одного метода."""
        return any(regex.match(path) for _, regex, _ in self._routes)


#: Глобальный роутер приложения.
router = Router()


def _make_handler(router_instance: Router) -> type[BaseHTTPRequestHandler]:
    """Построить класс обработчика :mod:`http.server` для роутера."""

    class ProjectFlowHandler(BaseHTTPRequestHandler):
        """HTTP-обработчик, транслирующий запросы в роутер."""

        server_version = f"{settings.app_name}/{settings.app_version}"
        protocol_version = "HTTP/1.1"

        # --- служебное ---

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            """Подавить стандартный лог, если отладка выключена."""
            if settings.debug:
                super().log_message(fmt, *args)

        def _read_body(self) -> tuple[dict[str, Any], bytes]:
            """Прочитать и разобрать тело запроса как JSON."""
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}, b""
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ProjectFlowError("Тело запроса не является корректным JSON", 400) from exc
            if not isinstance(parsed, dict):
                raise ProjectFlowError("Тело запроса должно быть JSON-объектом", 400)
            return parsed, raw

        def _build_request(self) -> Request:
            """Собрать объект :class:`Request` из данных запроса."""
            parsed_url = urlparse(self.path)
            body, raw = self._read_body()
            return Request(
                method=self.command,
                path=parsed_url.path,
                query=parse_qs(parsed_url.query),
                headers={key.lower(): value for key, value in self.headers.items()},
                body=body,
                raw_body=raw,
            )

        def _send(self, response: Response) -> None:
            """Отправить ответ клиенту."""
            if response.raw is not None:
                data = response.raw
            elif response.status == 204 or response.payload is None:
                data = b""
            else:
                data = json.dumps(response.payload, ensure_ascii=False).encode("utf-8")

            self.send_response(response.status)
            if data:
                self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if data and self.command != "HEAD":
                self.wfile.write(data)

        def _dispatch(self) -> None:
            """Обработать запрос: маршрутизация, вызов, обработка ошибок."""
            try:
                request = self._build_request()
                handler, path_params = router_instance.resolve(request.method, request.path)
                if handler is None:
                    if router_instance.has_path(request.path):
                        self._send(Response.json(
                            {"error": "method_not_allowed",
                             "message": f"Метод {request.method} не поддерживается"},
                            status=405,
                        ))
                        return
                    self._send(Response.json(
                        {"error": "not_found",
                         "message": f"Маршрут {request.path} не найден"},
                        status=404,
                    ))
                    return

                request.path_params = path_params
                response = handler(request)
                if not isinstance(response, Response):
                    response = Response.json(response)
                self._send(response)

            except ProjectFlowError as exc:
                self._send(Response.json(exc.to_dict(), status=exc.status_code))
            except Exception:  # noqa: BLE001 - защитная ветка верхнего уровня
                if settings.debug:
                    traceback.print_exc()
                self._send(Response.json(
                    {"error": "internal_error",
                     "message": "Внутренняя ошибка сервера"},
                    status=500,
                ))

        def do_GET(self) -> None:  # noqa: N802 - требование http.server
            """Обработать GET-запрос."""
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            """Обработать POST-запрос."""
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            """Обработать PUT-запрос."""
            self._dispatch()

        def do_PATCH(self) -> None:  # noqa: N802
            """Обработать PATCH-запрос."""
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            """Обработать DELETE-запрос."""
            self._dispatch()

    return ProjectFlowHandler


def create_server(host: str | None = None, port: int | None = None,
                  router_instance: Router | None = None) -> ThreadingHTTPServer:
    """Создать HTTP-сервер, привязанный к роутеру.

    :param host: адрес прослушивания
    :param port: порт; ``0`` выбирает свободный порт (удобно в тестах)
    """
    active_router = router_instance or router
    handler_class = _make_handler(active_router)
    return ThreadingHTTPServer((host or settings.host, port if port is not None else settings.port),
                               handler_class)
