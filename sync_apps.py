#!/usr/bin/env python3
"""Match the supplied app PNGs and locally recorded desktop application IDs."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image

import build_theme as builder


CONTROL_CONTEXTS = {"actions", "status", "emblems", "notifications", "ui"}
GENERIC_NAMES = {"agent", "calendar", "camera", "clock", "computer", "contacts", "filemanager", "help", "home", "java", "music", "password", "python", "qt", "terminal", "texteditor", "video", "webbrowser"}
ARTWORK_OVERRIDES = {"text-editor", "accessories-text-editor"}


def excluded_names():
    """Keep control artwork out of the application-name import."""
    excluded = {}
    for path in builder.SOURCE.rglob("*"):
        if path.suffix in {".png", ".svg", ".xpm"} and CONTROL_CONTEXTS.intersection(path.relative_to(builder.SOURCE).parts[:-1]):
            excluded[path.stem] = "also supplied as action, status, emblem or notification artwork"
    for directory in builder.inherited_directories():
        for path in directory.rglob("*"):
            if path.suffix in {".png", ".svg", ".xpm"} and (
                CONTROL_CONTEXTS.intersection(path.relative_to(directory).parts[:-1])
                or "-symbolic" in path.stem
            ):
                excluded[path.stem] = "inherited control"
                # A full-color base name can also be requested as an action.
                if CONTROL_CONTEXTS.intersection(path.relative_to(directory).parts[:-1]):
                    excluded[path.stem.removesuffix("-symbolic")] = "inherited control"
    return excluded


def source_apps():
    excluded = excluded_names()
    rows = []
    for path in sorted((builder.SOURCE / "128x128/apps").glob("*.png")):
        row = {"name": path.stem, "source": str(path.relative_to(builder.SOURCE))}
        if any(character.isspace() for character in path.stem):
            row["excluded"] = "icon name contains whitespace (rejected by GTK icon cache)"
        elif path.stem in excluded:
            row["excluded"] = excluded[path.stem]
        elif not path.is_file():
            row["excluded"] = "broken source symlink"
        else:
            with Image.open(path) as image:
                image.verify()
                row["maximum_size"] = max(image.size)
        rows.append(row)
    return rows


def name_index(manifest):
    return {alias: name for name, entry in manifest["apps"].items() for alias in [name, *entry["aliases"]]}


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def catalog_components():
    # Work from cached metadata; rebuilding the resulting pack needs no catalog.
    roots = [Path("/var/lib/flatpak"), builder.data_home() / "flatpak"]
    seen = set()
    for root in roots:
        for catalog in sorted(root.glob("appstream/*/*/active/appstream.xml")):
            for _, component in ET.iterparse(catalog, events=("end",)):
                if component.tag != "component":
                    continue
                app_id = component.findtext("id", "").removesuffix(".desktop")
                if component.get("type") in {"desktop-application", "desktop"} and app_id not in seen:
                    seen.add(app_id)
                    label = next((node.text or "" for node in component.findall("name")
                                  if "{http://www.w3.org/XML/1998/namespace}lang" not in node.attrib), "")
                    yield app_id, label
                component.clear()


def synchronize(manifest):
    rows = source_apps()
    by_name = name_index(manifest)
    fingerprints = {}

    def fingerprint(source):
        path = (builder.SOURCE / source).resolve()
        if path not in fingerprints:
            with Image.open(path) as image:
                fingerprints[path] = (image.size, hashlib.sha256(image.convert("RGBA").tobytes()).digest())
        return fingerprints[path]

    # Prefer an app's own supplied image over an older generic app alias.
    # Keep the explicitly selected TextEdit artwork for text-editor names.
    for row in rows:
        alias = row["name"]
        if "excluded" in row or alias not in by_name or alias in ARTWORK_OVERRIDES:
            continue
        current = by_name[alias]
        entry = manifest["apps"][current]
        if fingerprint(entry["source"]) == fingerprint(row["source"]):
            continue
        if alias == current:
            entry["source"] = row["source"]
            continue
        transferred = [name for name in entry["aliases"]
                       if name == alias or ("." in name and normalized(name.rsplit(".", 1)[-1]) == normalized(alias))]
        entry["aliases"] = [name for name in entry["aliases"] if name not in transferred]
        manifest["apps"][alias] = {"source": row["source"], "label": alias,
                                   "aliases": [name for name in transferred if name != alias]}
        for name in transferred:
            by_name[name] = alias

    all_names = {alias for icons in manifest.values() for name, entry in icons.items() for alias in [name, *entry["aliases"]]}
    by_source = {}
    for name, entry in manifest["apps"].items():
        by_source.setdefault((builder.SOURCE / entry["source"]).resolve(), name)
    for row in rows:
        if "excluded" in row or row["name"] in all_names:
            continue
        path = builder.SOURCE / row["source"]
        target = by_source.get(path.resolve())
        if target is None:
            target = row["name"]
            manifest["apps"][target] = {"source": row["source"], "label": row["name"], "aliases": []}
            by_source[path.resolve()] = target
        else:
            manifest["apps"][target]["aliases"].append(row["name"])
        all_names.add(row["name"])

    by_name = name_index(manifest)
    by_normalized = defaultdict(set)
    for row in rows:
        if "excluded" not in row and row["name"] in by_name and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.-]*[A-Za-z0-9+]", row["name"]):
            by_normalized[normalized(row["name"])].add(by_name[row["name"]])
    excluded = excluded_names()

    def add_alias(alias, target):
        if not alias or "/" in alias or "\\" in alias or "symbolic" in alias or alias in excluded or any(character.isspace() for character in alias):
            return
        if alias in all_names:
            return
        manifest["apps"][target]["aliases"].append(alias)
        all_names.add(alias)
        by_name[alias] = target

    # A few supplied filenames use capitals even though launchers use lowercase.
    for row in rows:
        if "excluded" not in row and row["name"] in by_name:
            add_alias(row["name"].casefold(), by_name[row["name"]])

    catalog_matches = []
    for app_id, label in catalog_components():
        # Require agreement between the app name (or its first whole word,
        # e.g. "OpenShot Video Editor") and the ID's final part.
        id_name = normalized(app_id.rsplit(".", 1)[-1])
        if id_name in GENERIC_NAMES:
            continue
        title_names = {normalized(label), normalized(label.split()[0])} if label else set()
        id_matches = by_normalized.get(id_name, set())
        if len(id_matches) == 1 and id_name in title_names:
            target = next(iter(id_matches))
            if app_id in by_name and by_name[app_id] != target:
                continue
            add_alias(app_id, target)
            catalog_matches.append({"id": app_id, "name": label, "icon": target})

    launcher_matches = []
    for filename, path in sorted(builder.launchers().items()):
        entry = builder.desktop_entry(path.read_text())
        icon = entry.get("Icon", "")
        target = by_name.get(icon)
        if target is None:
            candidates = by_normalized.get(normalized(Path(icon).stem if icon.startswith("/") else icon), set())
            if len(candidates) == 1:
                target = next(iter(candidates))
            elif re.fullmatch(r"java\d+-openjdk", icon) and "Java" in entry.get("Name", ""):
                # The installed OpenJDK launchers share a versioned Java name.
                target = by_name.get("java")
        if target is None:
            continue
        if icon.startswith("/"):
            # Theme lookup cannot intercept an absolute path.
            files = manifest["apps"][target].setdefault("desktop_files", [])
            if filename not in files:
                files.append(filename)
        else:
            add_alias(icon, target)
        add_alias(Path(filename).stem, target)
        launcher_matches.append({"desktop_file": filename, "icon": target})

    for entry in manifest["apps"].values():
        entry["aliases"] = sorted(entry["aliases"])
    return rows, sorted(catalog_matches, key=lambda row: row["id"]), launcher_matches


def audit(manifest, rows=None):
    by_name = {alias: (name, entry) for icons in manifest.values() for name, entry in icons.items() for alias in [name, *entry["aliases"]]}
    result = []
    for row in rows if rows is not None else source_apps():
        row = dict(row)
        if row["name"] in by_name:
            name, entry = by_name[row["name"]]
            row.update({"icon": name, "mapped_source": entry["source"], "status": "mapped"})
        elif "excluded" in row:
            row["status"] = "excluded"
        else:
            row["status"] = "missing"
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check without changing the manifest or report")
    args = parser.parse_args()
    manifest_path = builder.ROOT / "icons.json"
    previous = json.loads(manifest_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    rows, catalog_matches, launcher_matches = synchronize(manifest)
    builder.check_manifest(manifest)
    source_rows = audit(manifest, rows)
    assert not [row for row in source_rows if row["status"] == "missing"]
    report = {
        "source_png_names": len(rows),
        "mapped_source_names": sum(row["status"] == "mapped" for row in source_rows),
        "excluded_source_names": sum(row["status"] == "excluded" for row in source_rows),
        "source_apps": source_rows,
        "catalog_matches": catalog_matches,
        "launcher_matches": launcher_matches,
    }
    if args.check:
        assert manifest == previous, "Run python3 sync_apps.py to update application mappings"
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        (builder.ROOT / "app-source-coverage.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Source app names: {report['mapped_source_names']} mapped, {report['excluded_source_names']} excluded; {len(catalog_matches)} catalog ID matches")


if __name__ == "__main__":
    main()
