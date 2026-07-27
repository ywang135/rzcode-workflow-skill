#!/usr/bin/env python3
"""Upload local images to a RZCode project via the rzcode_upload_images MCP tool.

This script avoids loading image base64 strings into the LLM context by handling
image discovery, encoding, and MCP upload locally.

Usage:
    export RZCODE_API_KEY="sk.<shared_token>.<random_string>"
    python upload_image_files.py --project-id 123 /path/to/screenshots/
    python upload_image_files.py --project-id 123 --url http://localhost:5000 --api-key <key> img1.png img2.jpg
    python upload_image_files.py --project-id 123 --type screenshot --diagram-type flowchart --diagram-description "Login flow" diagram.svg
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import response

import requests

MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
VALID_IMAGE_TYPES = {"screenshot", "diagram"}
DIAGRAM_TYPES = [
    "architecture_layer",
    "module_design",
    "topology",
    "sequence",
    "state_machine",
    "use_case",
    "class_uml",
    "er_diagram",
    "deployment",
    "interface_call",
]
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024
DEFAULT_HEADERS = {
    "Accept": "text/event-stream, application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
}


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    return args.api_key or os.getenv("RZCODE_API_KEY")


def _resolve_url(args: argparse.Namespace) -> str:
    return args.url or os.getenv("RZCODE_URL") or "https://rzcode.vip"


def _validate_image_type(value: str) -> str:
    if value not in VALID_IMAGE_TYPES:
        raise argparse.ArgumentTypeError(
            f"--type must be one of {sorted(VALID_IMAGE_TYPES)}, got {value!r}"
        )
    return value


DIAGRAM_TYPES_HELP = (
    "Diagram type (only used when --type=diagram). "
    "Built-in options: " + ", ".join(DIAGRAM_TYPES) + ". "
    "Custom types are allowed, but you must also provide --diagram-description."
)


def _load_image_metadata(metadata_path: Path | None) -> dict[str, dict[str, str]]:
    """Load optional per-image metadata mapping filename -> metadata dict.

    Expected JSON shape:
        {
            "diagram.svg": {
                "type": "diagram",
                "diagram_type": "flowchart",
                "diagram_description": "Login flow"
            },
            "screen.png": {
                "type": "screenshot",
                "diagram_type": "",
                "diagram_description": "Main dashboard"
            }
        }
    """
    if not metadata_path:
        return {}
    metadata_path = metadata_path.expanduser().resolve()
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    with metadata_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Image metadata JSON must be a mapping of filename -> metadata")

    valid: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            valid[str(key)] = {
                "type": str(value.get("type", "")),
                "diagram_type": str(value.get("diagram_type", "")),
                "diagram_description": str(value.get("diagram_description", "")),
            }
    return valid


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


def _encode_images(
    image_paths: list[Path],
    metadata: dict[str, dict[str, str]],
    default_type: str = "screenshot",
    default_diagram_type: str = "",
    default_diagram_description: str = "",
) -> list[tuple[str, str, dict[str, Any], Path]]:
    """Return [(image_name, base64_content, metadata_dict, original_path)] for valid images."""
    encoded: list[tuple[str, str, dict[str, Any], Path]] = []
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

        meta = metadata.get(path.name, metadata.get(name, {}))
        img_type = meta.get("type", default_type) or default_type
        diagram_type = meta.get("diagram_type", default_diagram_type)
        diagram_description = meta.get("diagram_description", default_diagram_description)

        if img_type not in VALID_IMAGE_TYPES:
            raise ValueError(
                f"Invalid type {img_type!r} for image {path.name}. "
                f"Must be one of {sorted(VALID_IMAGE_TYPES)}."
            )
        if img_type == "diagram" and not diagram_type:
            raise ValueError(
                f"--diagram-type is required when type=diagram for image {path.name}."
            )
        if diagram_type and diagram_type not in DIAGRAM_TYPES and not diagram_description:
            raise ValueError(
                f"--diagram-description is required for custom diagram_type {diagram_type!r} "
                f"for image {path.name}."
            )

        payload_meta: dict[str, Any] = {"type": img_type}
        if img_type == "diagram":
            payload_meta["diagram_type"] = diagram_type
            if diagram_description:
                payload_meta["diagram_description"] = diagram_description

        encoded.append((name, b64, payload_meta, path))
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


def _extract_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    """Extract rzcode_upload_images payload from MCP JSON-RPC response.

    Handles multiple envelope shapes used by MCP servers:
      1) {"result": {"result": {...}}}
      2) {"result": {...}}
      3) {"result": {"content": [{"type": "text", "text": "{...}"}]}}
    """
    outer = response.get("result")
    if not isinstance(outer, dict):
        return {}

    nested = outer.get("result")
    if isinstance(nested, dict):
        return nested

    if "project_id" in outer or "uploaded_files" in outer:
        return outer

    content = outer.get("content")
    if not isinstance(content, list):
        return {}

    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if isinstance(parsed.get("result"), dict):
                return parsed["result"]
            return parsed

    return {}


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
        "--type",
        default="screenshot",
        type=_validate_image_type,
        help="Image type: screenshot or diagram (default: auto / not provided)",
    )
    parser.add_argument(
        "--diagram-type",
        default="",
        help=DIAGRAM_TYPES_HELP,
    )
    parser.add_argument(
        "--diagram-description",
        default="",
        help="Diagram description (required when --diagram-type is a custom type not in the built-in list)",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        help="JSON file mapping image filename to metadata {type, diagram_type, diagram_description}",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Image files or folders containing images (.png, .jpg, .jpeg, .svg supported)",
    )
    args = parser.parse_args()

    # Validate argument combinations before touching API/network state.
    if args.type == "diagram" and not args.diagram_type:
        print(
            "Error: --diagram-type is required when --type=diagram.",
            file=sys.stderr,
        )
        return 1

    if args.type == "screenshot" and args.diagram_type:
        print(
            "Error: --diagram-type is not required when --type=screenshot.",
            file=sys.stderr,
        )
        return 1

    if (
        args.diagram_type
        and args.diagram_type not in DIAGRAM_TYPES
        and not args.diagram_description
    ):
        print(
            f"Error: --diagram-description is required when using custom --diagram-type {args.diagram_type!r} "
            f"(not in built-in list: {', '.join(DIAGRAM_TYPES)}).",
            file=sys.stderr,
        )
        return 1

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
    metadata = _load_image_metadata(args.metadata)
    encoded_images = _encode_images(
        image_paths,
        metadata,
        args.type,
        args.diagram_type,
        args.diagram_description,
    )
    if not encoded_images:
        print("No images passed validation.", file=sys.stderr)
        return 1

    # Convert to list of [name, base64, metadata] tuples for the MCP tool schema.
    images_payload = [
        [name, b64, meta]
        for name, b64, meta, _ in encoded_images
    ]

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

    result = _extract_tool_result(response)
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
