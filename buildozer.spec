[app]
title = Aurora
package.name = aurora
package.domain = org.aurora.ai
source.dir = .
source.include_exts = py,json,db,txt
version = 1.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0

# Android permissions needed by Aurora's optional web engine.
android.permissions = INTERNET

# Keep SQLite and Aurora data inside the app's writable storage.
android.api = 34
android.minapi = 23

[buildozer]
log_level = 2
warn_on_root = 1
