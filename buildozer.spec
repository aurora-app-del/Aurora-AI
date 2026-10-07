[app]
title = Aurora
package.name = aurora
package.domain = org.aurora.ai
source.dir = .
source.include_exts = py,json,db,txt
version = 2.0
requirements = python3==3.13.11,hostpython3==3.13.11,kivy,pyjnius
orientation = portrait
fullscreen = 0

# Aurora 2.0: internet + microfone.
android.permissions = INTERNET,RECORD_AUDIO
android.api = 34
android.minapi = 23
android.archs = arm64-v8a

# Mantém o projeto simples para python-for-android.
[buildozer]
log_level = 2
warn_on_root = 1
