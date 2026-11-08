# Cheetah artwork

The main icon artwork is from **b00merang / B00merang Artwork**, checked out
unmodified in the pinned `artwork/` Git submodule (or the original sibling source folder). Its local Git
repository identifies the source as
[B00merang-Artwork/Mac-OS-X-Cheetah](https://github.com/B00merang-Artwork/Mac-OS-X-Cheetah),
at commit `2d4ae3f64f80701e3bef23f6211c9a3bd8ad41c8` ("Initial upload").
The source index credits "Mac-X-Cheetah by Elbullazul" and notes its derivation
from Mac-X-Lion. This build retains that attribution and grants no new license
to the supplied Apple or third-party artwork.

`icons.json`, copied into the built theme as `sources.json`, lists each exact
original PNG used for the 989 application, folder, drive and file-type mappings.
The mapping and build tools are adapted from the local `../Lion-GNOME` project.
The Cheetah repository supplies the artwork, including its striped blue folders.
Many other images are shared with the Lion source and can depict later releases.
The Desktop mapping uses `128x128/places/folder-desktop.png` for `user-desktop`
and its aliases, selecting the Cheetah artwork instead of the source's later
macOS `user-desktop.png` image.

`sync_apps.py` imports the usable app PNG names, preserves source symlink aliases,
and records source coverage in `app-source-coverage.json`. Modern app IDs are
matched against names in the locally cached AppStream catalog; installed desktop
files supply their actual requested icon names. Control-name collisions and the
broken `jscalibrator.png` source link are excluded, along with the cache-invalid
name `display capplet.png` (the valid `display-capplet.png` is included).
Explicit TextEdit mappings
continue to use the selected `package_editors.png` artwork.

The search artwork used for All Apps is the supplied
`128x128/apps/panel-searchtool.png`. `dock-source.json` records its path,
repository, pinned commit and SHA-256. It is installed only under Dash to Dock's
session-specific `view-app-grid-user-symbolic.png` name. It remains a full-color
PNG, preserving the supplied shading, and opens the normal GNOME application
grid. The shared `view-app-grid-symbolic` control remains inherited.

PNGs are downsampled to transparent square canvases at 16, 22, 24, 32, 48, 64, 96
and 128 pixels, preserving aspect ratio. No source artwork is upscaled. Small
sizes use the full-color designs rather than the source's separate small-icon
set. App sources smaller than an output size omit that size; GTK resolves larger
requests to available artwork. The generated index declares the fixed-size
directories.

Missing artwork and symbolic controls are inherited from installed Adwaita and
its normal fallback chain.
