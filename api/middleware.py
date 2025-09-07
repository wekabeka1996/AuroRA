"""
Compatibility middleware shims for tests importing api.middleware.
These are lightweight and mirror the expected interfaces from tests.
Main production logic lives in api.service middleware.
"""
from __future__ import annotations
from typing import Callable, Dict
import time
import os
from fastapi import Request
from starlette.responses import JSONResponse


class LeakyBucket:
	def __init__(self, capacity: float = 60.0, leak_rate: float = 60.0):
		self.capacity = float(capacity)
		self.leak_rate = float(leak_rate)  # tokens per second
		self.tokens = float(capacity)
		self.ts = time.time()

	def _refill(self) -> None:
		now = time.time()
		dt = max(0.0, now - self.ts)
		if dt > 0:
			self.tokens = min(self.capacity, self.tokens + dt * self.leak_rate)
			self.ts = now

	def allow(self) -> bool:
		self._refill()
		if self.tokens >= 1.0:
			self.tokens -= 1.0
			return True
		return False


class AuthMiddleware:
	def __init__(self, app, token_getter: Callable[[], str | None] | None = None):
		self.app = app
		# Store resolved token for tests to introspect
		self.auth_token = (token_getter() if token_getter else None) or os.getenv('AURORA_API_TOKEN')

	async def __call__(self, scope, receive, send):
		# Delegate to dispatch for ASGI compat
		async def call_next(request: Request):
			await self.app(scope, receive, send)
		await self.dispatch(Request(scope, receive), call_next)

	async def dispatch(self, request: Request, call_next):
		# For tests, only enforce token on mutating endpoints
		method = (request.method or 'GET').upper()
		path = request.url.path
		mutating = method in {'POST', 'PUT', 'PATCH', 'DELETE'}
		if mutating:
			x_auth = request.headers.get('X-Auth-Token')
			if not self.auth_token:
				return JSONResponse({"detail": "AURORA_API_TOKEN not configured"}, status_code=503)
			if not x_auth:
				return JSONResponse({"detail": "Missing X-Auth-Token"}, status_code=401)
			if x_auth != self.auth_token:
				return JSONResponse({"detail": "Forbidden"}, status_code=403)
		return await call_next(request)


class RateLimitMiddleware:
	def __init__(self, app, general_rps: float = 60.0, mutating_rps: float = 10.0):
		self.app = app
		self.general_rps = float(general_rps)
		self.mutating_rps = float(mutating_rps)
		self.ip_buckets: Dict[str, LeakyBucket] = {}
		self.mutating_buckets: Dict[str, LeakyBucket] = {}

	def _client_ip(self, request: Request) -> str:
		ip = (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
		if not ip:
			ip = request.client.host if request.client else ''
		if ip in {'', 'testclient'}:
			ip = '127.0.0.1'
		return ip

	async def __call__(self, scope, receive, send):
		async def call_next(request: Request):
			await self.app(scope, receive, send)
		await self.dispatch(Request(scope, receive), call_next)

	async def dispatch(self, request: Request, call_next):
		method = (request.method or 'GET').upper()
		path = request.url.path
		ip = self._client_ip(request)
		# Init buckets lazily
		b = self.ip_buckets.get(ip)
		if b is None:
			b = self.ip_buckets[ip] = LeakyBucket(capacity=self.general_rps, leak_rate=self.general_rps)
		if not b.allow():
			return JSONResponse({"detail": "Too Many Requests"}, status_code=429)
		if method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
			mb = self.mutating_buckets.get(ip)
			if mb is None:
				mb = self.mutating_buckets[ip] = LeakyBucket(capacity=self.mutating_rps, leak_rate=self.mutating_rps)
			if not mb.allow():
				return JSONResponse({"detail": "Too Many Requests"}, status_code=429)
		return await call_next(request)

