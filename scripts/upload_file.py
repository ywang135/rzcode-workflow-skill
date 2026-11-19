#!/usr/bin/env python3
"""Upload a local file to a RZCode project via the project upload API.

Used by the AIGC precheck flow to upload the source code .docx before running
rzcode_create_or_get_ongoing_task(task_type=PRECHECK_SOURCE_CODE_AIGC).

Usage:
    export RZCODE_API_KEY="sk.<shared_token>.<random_string>"
    python upload_file.py --project-id 123 --file-type source_code /path/to/source.docx
    python upload_file.py --project-id 123 --url http://localhost:5000 --api-key <key> source.docx
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

DEFAULT_URL = "https://rzcode.vip"
FILE_TYPES = ["source_code", "guide", "design", "help", "signature_page", "application_info"]
REQUEST_TIMEOUT_SECONDS = 300


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    return args.api_key or os.getenv("RZCODE_API_KEY")


def _resolve_url(args: argparse.Namespace) -> str:
    return (args.url or os.getenv("RZCODE_URL") or DEFAULT_URL).rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload a local file to a RZCode project via POST /api/projects/<id>/upload/<file_type>."
    )
    parser.add_argument("--project-id", required=True, type=int, help="RZCode project ID")
    parser.add_argument(
        "--file-type",
        default="source_code",
        choices=FILE_TYPES,
        help="Document slot to upload into (default: source_code)",
    )
    parser.add_argument("--url", help=f"RZCode base URL (default: {DEFAULT_URL})")
    parser.add_argument("--api-key", help="API key (or set RZCODE_API_KEY env var)")
    parser.add_argument("path", help="Local file to upload")
    args = parser.parse_args()

    api_key = _resolve_api_key(args)
    if not api_key:
        print(
            "Error: API key is required. Use --api-key or set RZCODE_API_KEY env var.",
            file=sys.stderr,
        )
        return 1

    file_path = Path(args.path).expanduser().resolve()
    if not file_path.is_file():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        return 1

    url = f"{_resolve_url(args)}/api/projects/{args.project_id}/upload/{args.file_type}"
    print(f"Uploading {file_path.name} to project {args.project_id} ({args.file_type})...")
    with file_path.open("rb") as f:
        resp = requests.post(
            url,
            headers={"X-API-Key": api_key},
            files={"file": (file_path.name, f)},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    if resp.status_code != 200:
        print(f"Upload failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
        return 1

    data = resp.json()
    print("Upload successful.")
    print(f"  project_id: {data.get('id', args.project_id)}")
    print(f"  doc_type: {data.get('doc_type', args.file_type)}")
    print(f"  path: {data.get('path', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
