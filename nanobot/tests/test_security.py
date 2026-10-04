from __future__ import annotations

import socket

import pytest

import app as nanobot_app

ALLOWED = ["sam.gov", "usaspending.gov"]


@pytest.mark.parametrize("url", [
    "https://sam.gov/opp/123",
    "http://sam.gov/opp/123",
    "https://www.sam.gov/opp/123",
    "https://api.v2.usaspending.gov/award",
    "https://SAM.GOV/opp",
    "https://sam.gov:8443/opp",
    "https://sam.gov",
])
def test_allowed_urls(url: str) -> None:
    assert nanobot_app.is_allowed_url(url, ALLOWED)


@pytest.mark.parametrize("url", [
    "https://evilsam.gov/opp",             # suffix match without a dot boundary
    "https://sam.gov.evil.com/opp",        # allowed domain only as a prefix
    "https://evil.com/sam.gov",            # allowed domain only in the path
    "https://evil.com/?next=https://sam.gov",
    "https://sam.gov@evil.com/opp",        # userinfo trick: real host is evil.com
    "ftp://sam.gov/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "sam.gov/opp",                         # no scheme
    "//sam.gov/opp",
    "",
])
def test_rejected_urls(url: str) -> None:
    assert not nanobot_app.is_allowed_url(url, ALLOWED)


def test_empty_allowlist_rejects_everything() -> None:
    assert not nanobot_app.is_allowed_url("https://sam.gov/opp", [])


def fake_dns(monkeypatch, *ips: str) -> None:
    def getaddrinfo(host, port, **kwargs):
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
             (ip, 0, 0, 0) if ":" in ip else (ip, 0))
            for ip in ips
        ]
    monkeypatch.setattr(nanobot_app.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize("ip", ["8.8.8.8", "104.18.0.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(monkeypatch, ip: str) -> None:
    fake_dns(monkeypatch, ip)
    assert nanobot_app.host_is_public("example.test") is True


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "172.16.0.9", "192.168.1.1",
    "169.254.169.254",                     # cloud metadata endpoint
    "100.64.0.1",                          # carrier-grade NAT
    "0.0.0.0", "::1", "fe80::1", "fc00::1",
])
def test_non_public_addresses_are_rejected(monkeypatch, ip: str) -> None:
    fake_dns(monkeypatch, ip)
    assert nanobot_app.host_is_public("example.test") is False


def test_one_private_answer_among_public_ones_rejects_the_host(monkeypatch) -> None:
    fake_dns(monkeypatch, "8.8.8.8", "10.0.0.5")
    assert nanobot_app.host_is_public("example.test") is False


def test_resolution_failure_is_not_public(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(nanobot_app.socket, "getaddrinfo", boom)
    assert nanobot_app.host_is_public("nope.invalid") is False


def test_empty_resolution_is_not_public(monkeypatch) -> None:
    monkeypatch.setattr(nanobot_app.socket, "getaddrinfo", lambda *a, **k: [])
    assert nanobot_app.host_is_public("example.test") is False
