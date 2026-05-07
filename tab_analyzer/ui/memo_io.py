from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote


MEMO_MARKER = "<!-- TAB_ANALYZER_MEMO_V1 -->"
MMDX_MARKER = "TAB_ANALYZER_MMDX_V1"
MMDX_MANIFEST_NAME = "manifest.json"
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\n]+)\)")
HTML_IMAGE_PATTERN = re.compile(r"(<img\b[^>]*\bsrc=[\"'])([^\"']+)([\"'][^>]*>)", re.IGNORECASE)
SAFE_ASSET_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _measure_note_text(text: str | None) -> str:
    return (text or "").strip()


def _memo_path_for_tab(path: Path) -> Path:
    return path.with_name(f"memo_{path.name}.mmdx")


def _legacy_memo_path_for_tab(path: Path) -> Path:
    return path.with_name(f"memo_{path.name}.md")


def _memo_autosave_path(path: Path) -> Path:
    return path.with_name(f".memo_{path.name}.autosave.mmdx")


def _serialize_legacy_memos(source_path: Path | None, memos: dict[int, str]) -> str:
    source = source_path.name if source_path is not None else ""
    lines = [
        "# Tab Analyzer Memo",
        "",
        MEMO_MARKER,
        f"source: {source}",
        f"saved_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for number in sorted(memos):
        text = _measure_note_text(memos[number])
        if not text:
            continue
        lines.extend([f"## M{number}", "", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_memos(markdown: str) -> dict[int, str]:
    memos: dict[int, str] = {}
    current: int | None = None
    buffer: list[str] = []
    heading = re.compile(r"^##\s+M(\d+)\b")

    def flush() -> None:
        if current is None:
            return
        text = "\n".join(buffer).strip()
        if text:
            memos[current] = text

    for line in markdown.splitlines():
        match = heading.match(line.strip())
        if match:
            flush()
            current = int(match.group(1))
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    flush()
    return memos


def _write_memo_package(path: Path, source_path: Path | None, memos: dict[int, str], base_dirs: tuple[Path, ...] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Path] = {}
    manifest = {
        "format": MMDX_MARKER,
        "source": source_path.name if source_path is not None else "",
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MMDX_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for number in sorted(memos):
            text = _measure_note_text(memos[number])
            if not text:
                continue
            rewritten = _rewrite_memo_image_references(text, number, base_dirs, assets)
            archive.writestr(f"M{number}.md", rewritten.rstrip() + "\n")
        for archive_name, source in sorted(assets.items()):
            archive.write(source, archive_name)


def _read_memo_package(path: Path, extract_dir: Path | None = None) -> dict[int, str]:
    if path.suffix.lower() != ".mmdx":
        return _parse_memos(path.read_text(encoding="utf-8"))

    memos: dict[int, str] = {}
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir() or not _safe_zip_member(info.filename):
                continue
            member_path = PurePosixPath(info.filename.replace("\\", "/"))
            match = re.fullmatch(r"M(\d+)\.md", member_path.name)
            if match and len(member_path.parts) == 1:
                memos[int(match.group(1))] = archive.read(info).decode("utf-8").strip()
            if extract_dir is not None:
                target = extract_dir.joinpath(*member_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    return {number: text for number, text in memos.items() if _measure_note_text(text)}


def _safe_zip_member(name: str) -> bool:
    member_path = PurePosixPath(name.replace("\\", "/"))
    return not member_path.is_absolute() and ".." not in member_path.parts


def _rewrite_memo_image_references(text: str, measure_number: int, base_dirs: tuple[Path, ...], assets: dict[str, Path]) -> str:
    def markdown_replacer(match: re.Match[str]) -> str:
        raw_target = match.group(1)
        target = _image_target_from_markdown(raw_target)
        replacement = _memo_asset_reference(target, measure_number, base_dirs, assets)
        if replacement == target:
            return match.group(0)
        return match.group(0).replace(target, replacement, 1)

    def html_replacer(match: re.Match[str]) -> str:
        target = match.group(2)
        replacement = _memo_asset_reference(target, measure_number, base_dirs, assets)
        return f"{match.group(1)}{replacement}{match.group(3)}"

    text = MARKDOWN_IMAGE_PATTERN.sub(markdown_replacer, text)
    return HTML_IMAGE_PATTERN.sub(html_replacer, text)


def _image_target_from_markdown(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.strip("\"'")


def _memo_asset_reference(target: str, measure_number: int, base_dirs: tuple[Path, ...], assets: dict[str, Path]) -> str:
    source = _resolve_memo_asset(target, base_dirs)
    if source is None:
        return target
    archive_name = _unique_memo_asset_name(measure_number, source, assets)
    assets[archive_name] = source
    return archive_name


def _resolve_memo_asset(target: str, base_dirs: tuple[Path, ...]) -> Path | None:
    if _is_external_asset_reference(target):
        return None
    cleaned = unquote(target).strip().strip("\"'")
    if not cleaned:
        return None
    candidate = Path(cleaned)
    candidates = [candidate] if candidate.is_absolute() else [base / cleaned for base in base_dirs if base is not None]
    for item in candidates:
        try:
            resolved = item.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _is_external_asset_reference(target: str) -> bool:
    value = target.strip().lower()
    if not value or value.startswith("#"):
        return True
    if re.match(r"^[a-z]:[\\/]", value):
        return False
    return re.match(r"^[a-z][a-z0-9+.-]*:", value) is not None


def _unique_memo_asset_name(measure_number: int, source: Path, assets: dict[str, Path]) -> str:
    safe_name = SAFE_ASSET_PATTERN.sub("_", source.name).strip("._") or "image"
    stem = Path(safe_name).stem or "image"
    suffix = Path(safe_name).suffix
    candidate = f"M{measure_number}_{stem}{suffix}"
    counter = 2
    while candidate in assets and assets[candidate] != source:
        candidate = f"M{measure_number}_{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _render_markdown_preview(markdown_text: str) -> str | None:
    try:
        from markdown_editor.editor import MarkdownDocument
    except Exception:  # noqa: BLE001 - Markdown-Editor is optional at runtime until requirements are installed.
        return None
    try:
        document = MarkdownDocument()
        document.text = markdown_text
        return str(document.getHtml())
    except Exception:  # noqa: BLE001 - fallback to Qt's built-in Markdown renderer.
        return None


