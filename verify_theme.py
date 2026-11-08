#!/usr/bin/env python3
"""Check generated PNGs and actual GTK 3/4 icon lookup and inheritance."""

import argparse
import configparser
import json
from pathlib import Path

from PIL import Image

import build_theme as builder
import sync_apps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme-dir", type=Path, default=builder.ROOT / "build" / builder.THEME)
    parser.add_argument("--gtk-version", choices=("3.0", "4.0"), default="4.0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    theme_dir = args.theme_dir.resolve()
    manifest = json.loads((builder.ROOT / "icons.json").read_text())
    builder.check_manifest(manifest)
    assert (theme_dir / builder.MARKER).is_file(), "Missing generated-theme marker"
    assert json.loads((theme_dir / "sources.json").read_text()) == manifest
    source_audit = sync_apps.audit(manifest)
    assert not [row for row in source_audit if row["status"] == "missing"], "Unmapped source app names"
    index = configparser.ConfigParser(interpolation=None)
    index.read(theme_dir / "index.theme")
    assert index["Icon Theme"]["Name"] == builder.THEME
    assert index["Icon Theme"]["Inherits"] == builder.FALLBACK
    directories = index["Icon Theme"]["Directories"].split(",")
    assert set(directories) == {
        f"{size}x{size}/{context}" for size in builder.SIZES for context in manifest
    }
    files = 0
    names = {}
    for context, icons in manifest.items():
        for name, entry in icons.items():
            with Image.open(builder.SOURCE / entry["source"]) as source:
                maximum_size = max(source.size)
            for alias in [name, *entry["aliases"]]:
                names[alias] = context
                for size in builder.SIZES:
                    path = theme_dir / f"{size}x{size}" / context / f"{alias}.png"
                    if size > maximum_size:
                        assert not path.exists(), f"Upscaled icon: {path}"
                        continue
                    assert path.is_file(), f"Missing/broken icon: {path}"
                    assert path.resolve().is_relative_to(theme_dir), f"External link: {path}"
                    if alias != name:
                        assert path.is_symlink() and path.readlink() == Path(f"{name}.png")
                    else:
                        with Image.open(path) as image:
                            image.load()
                            assert image.size == (size, size), f"Incorrect dimensions: {path}"
                            assert image.mode == "RGBA", f"Missing transparency support: {path}"
                            expected = builder.extract_frame(builder.SOURCE / entry["source"], size)
                            assert image.tobytes() == expected.tobytes(), f"Incorrect source artwork: {path}"
                    files += 1
    names[builder.DOCK_ICON] = "apps"
    for size in builder.SIZES:
        with Image.open(theme_dir / f"{size}x{size}" / "apps" / f"{builder.DOCK_ICON}.png") as image:
            image.load()
            assert image.size == (size, size) and image.mode == "RGBA"
            assert image.tobytes() == builder.extract_frame(builder.DOCK_SOURCE, size).tobytes()
        files += 1

    import gi

    gi.require_version("Gtk", args.gtk_version)
    from gi.repository import Gtk

    theme = Gtk.IconTheme.new()
    baseline = Gtk.IconTheme.new()
    theme.set_search_path([str(theme_dir.parent), *theme.get_search_path()])
    baseline.set_search_path(theme.get_search_path())
    if args.gtk_version == "4.0":
        theme.set_theme_name(builder.THEME)
        baseline.set_theme_name(builder.FALLBACK)
    else:
        theme.set_custom_theme(builder.THEME)
        baseline.set_custom_theme(builder.FALLBACK)

    def lookup(icon_theme, name, size=32, scale=1):
        if args.gtk_version == "4.0":
            paintable = icon_theme.lookup_icon(name, None, size, scale, Gtk.TextDirection.NONE, Gtk.IconLookupFlags(0))
            file = paintable.get_file()
            return file.get_path() or file.get_uri() if file else None
        info = icon_theme.lookup_icon_for_scale(name, size, scale, Gtk.IconLookupFlags(0))
        return info.get_filename() if info else None

    lookups = 0
    for name, context in names.items():
        for size in builder.SIZES:
            for scale in (1, 2):
                result = lookup(theme, name, size, scale)
                assert result and Path(result).is_relative_to(theme_dir), f"Theme lookup fell through: {name}, {size}px, scale {scale}: {result}"
                assert Path(result).parent.name == context, f"Wrong context for {name}: {result}"
                assert Path(result).stem == name, f"Wrong icon selected for {name}: {result}"
                lookups += 1

    protected = {
        path.stem
        for directory in builder.inherited_directories()
        for path in directory.rglob("*")
        if path.suffix in {".svg", ".png", ".xpm"}
        and (
            {"actions", "status", "emblems", "ui"}.intersection(path.relative_to(directory).parts[:-1])
            or "-symbolic" in path.stem
        )
    } - builder.PLACE_OVERRIDE_EXCEPTIONS
    inherited = 0
    for name in sorted(protected):
        for size in (16, 32):
            expected, actual = lookup(baseline, name, size), lookup(theme, name, size)
            assert actual == expected, f"Inherited control changed: {name}: {actual} != {expected}"
            inherited += 1

    fallback_apps = 0
    missing = []
    for filename, path in builder.launchers().items():
        entry = builder.desktop_entry(path.read_text())
        if entry.get("NoDisplay", "false").lower() == "true" or entry.get("Hidden", "false").lower() == "true":
            continue
        icon = entry.get("Icon", "")
        if not icon:
            missing.append(filename)
        elif icon not in names and not icon.startswith("/"):
            assert lookup(theme, icon, 48) == lookup(baseline, icon, 48), f"Application fallback changed: {filename}"
            fallback_apps += 1
    report = {
        "theme": builder.THEME,
        "directory": str(theme_dir),
        "gtk_version": args.gtk_version,
        "icon_names": len(names),
        "mapped_source_app_names": sum(row["status"] == "mapped" for row in source_audit),
        "excluded_source_app_names": sum(row["status"] == "excluded" for row in source_audit),
        "png_files_and_aliases": files,
        "icon_lookups_at_scale_1_and_2": lookups,
        "inherited_control_lookups": inherited,
        "unchanged_application_fallbacks": fallback_apps,
        "preexisting_launchers_without_icons": missing,
        "result": "passed",
    }
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
