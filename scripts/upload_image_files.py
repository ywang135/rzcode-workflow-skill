#!/usr/bin/env python3
"""Upload local images to a RZCode project via the rzcode_upload_images MCP tool.

This script avoids loading image base64 strings into the LLM context by handling
image discovery, encoding, and MCP upload locally.

Usage:
    export RZCODE_API_KEY="sk.<shared_token>.<random_string>"
    python upload_image_files.py --project-id 123 /path/to/screenshots/
    python upload_image_files.py --project-id 123 --url http://localhost:5000 --api-key <key> img1.png img2.jpg
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path
from typing import Any

import requests

MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024
DEFAULT_HEADERS = {
    "Accept": "text/event-stream, application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
}


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    return args.api_key or os.getenv("RZCODE_API_KEY")


def _resolve_url(args: argparse.Namespace) -> str:
    return args.url or os.getenv("RZCODE_URL") or "https://rzcode.vip"


def _collect_image_paths(paths: list[str], recursive: bool) -> list[Path]:
    """Collect supported image files from files or directories."""
    image_paths: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            print(f"Warning: path not found: {raw}", file=sys.stderr)
            continue

        if path.is_file():
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                image_paths.append(path)
            else:
                print(
                    f"Warning: unsupported file type: {path} (expected {SUPPORTED_EXTENSIONS})",
                    file=sys.stderr,
                )
            continue

        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            for child in iterator:
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    image_paths.append(child)

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_paths: list[Path] = []
    for p in image_paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    return unique_paths


def _short_image_name(path: Path, index: int, used: set[str]) -> str:
    """Return a valid image name (<=20 chars) for the tool."""
    name = path.name
    if len(name) <= 20 and name not in used:
        return name

    ext = path.suffix.lower()
    # Keep extension within 20 chars; prefer 4-char ext plus 15-char prefix + separator.
    stem = f"img_{index:03d}"
    candidate = f"{stem}{ext}"
    if len(candidate) > 20:
        # Last resort: truncate extension to 3 chars if .jpeg -> .jpg
        ext = ".jpg" if ext == ".jpeg" else ext[:4]
        candidate = f"{stem}{ext}"
    return candidate


def _encode_images(image_paths: list[Path]) -> list[tuple[str, str, Path]]:
    """Return [(image_name, base64_content, original_path)] for valid images."""
    encoded: list[tuple[str, str, Path]] = []
    used_names: set[str] = set()
    for idx, path in enumerate(image_paths, start=1):
        size = path.stat().st_size
        if size > MAX_IMAGE_SIZE_BYTES:
            print(
                f"Skipping {path}: {size / (1024 * 1024):.2f}MB exceeds 4MB limit",
                file=sys.stderr,
            )
            continue

        name = _short_image_name(path, idx, used_names)
        used_names.add(name)
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        encoded.append((name, b64, path))
    return encoded


def _mcp_initialize(base_url: str, api_key: str) -> str:
    """Run MCP initialize handshake and return session id."""
    headers = dict(DEFAULT_HEADERS)
    headers["X-API-Key"] = api_key
    resp = requests.post(
        f"{base_url}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "rzcode-image-uploader"},
            },
        },
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"MCP initialize failed: {data['error']}")
    session_id = resp.headers.get("Mcp-Session-Id")
    if not session_id:
        raise RuntimeError("MCP initialize response missing Mcp-Session-Id header")
    return session_id


def _mcp_call_tool(
    base_url: str,
    api_key: str,
    session_id: str,
    name: str,
    args: dict[str, Any],
    req_id: int = 1,
) -> dict:
    """Call an MCP tool and return the JSON-RPC response object."""
    headers = dict(DEFAULT_HEADERS)
    headers["Mcp-Session-Id"] = session_id
    headers["X-API-Key"] = api_key
    resp = requests.post(
        f"{base_url}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "mcp.call",
            "params": {"kind": "tool", "name": name, "args": args},
        },
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _mcp_terminate(base_url: str, api_key: str, session_id: str) -> None:
    """Delete the MCP session."""
    try:
        requests.delete(
            f"{base_url}/mcp",
            headers={
                "Mcp-Session-Id": session_id,
                "X-API-Key": api_key,
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            },
            timeout=30,
        )
    except Exception as exc:
        print(f"Warning: failed to terminate MCP session: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload local images to a RZCode project via MCP rzcode_upload_images."
    )
    parser.add_argument(
        "--project-id", required=True, type=int, help="RZCode project ID"
    )
    parser.add_argument(
        "--url",
        default="https://rzcode.vip",
        help="RZCode base URL (default: https://rzcode.vip)",
    )
    parser.add_argument(
        "--api-key",
        help="API key (or set RZCODE_API_KEY env var)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan directories for images",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Image files or folders containing images",
    )
    args = parser.parse_args()

    api_key = _resolve_api_key(args)
    base_url = _resolve_url(args)

    if not api_key:
        print(
            "Error: API key is required. Use --api-key or set RZCODE_API_KEY env var.",
            file=sys.stderr,
        )
        return 1

    image_paths = _collect_image_paths(args.paths, args.recursive)
    if not image_paths:
        print("No supported image files found.", file=sys.stderr)
        return 1

    print(f"Found {len(image_paths)} image(s) to upload.")
    encoded_images = _encode_images(image_paths)
    if not encoded_images:
        print("No images passed validation.", file=sys.stderr)
        return 1

    # Convert to list of [name, base64] pairs for the MCP tool JSON schema.
    images_payload = [[name, b64] for name, b64, _ in encoded_images]

    print(f"Uploading {len(images_payload)} image(s) to project {args.project_id}...")
    session_id = _mcp_initialize(base_url, api_key)
    try:
        response = _mcp_call_tool(
            base_url,
            api_key,
            session_id,
            "rzcode_upload_images",
            {"project_id": args.project_id, "images": images_payload},
        )
    finally:
        _mcp_terminate(base_url, api_key, session_id)

    if "error" in response:
        print(f"Upload failed: {response['error']}", file=sys.stderr)
        return 1

    result = response.get("result", {}).get("result", {})
    print("Upload successful.")
    print(f"  project_id: {result.get('project_id', args.project_id)}")
    print(f"  uploaded_files: {result.get('uploaded_files', [])}")
    print(f"  images_count: {result.get('images_count', 0)}")
    print(f"  new_meta_count: {result.get('new_meta_count', 0)}")
    if result.get("image_extraction_task_id"):
        print(f"  image_extraction_task_id: {result['image_extraction_task_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
