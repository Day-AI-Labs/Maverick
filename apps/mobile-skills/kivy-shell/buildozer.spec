# Buildozer spec for the Maverick mobile-skills Kivy shell (Android).
#
# Building the APK is a MAINTAINER ACT on a Linux host with the buildozer
# toolchain (Android SDK/NDK are downloaded by buildozer on first run):
#
#   pip install buildozer cython
#   cd apps/mobile-skills/kivy-shell
#   cp ../../../packages/maverick-core/maverick/disagreement.py .   # bundle the skill
#   buildozer android debug
#
# buildozer packages source.dir only, which is why the pure skill module is
# copied in rather than referenced across the repo. iOS is NOT driven by
# this file: that path is kivy-ios + Xcode (see ../README.md).

[app]
title = Maverick Skills
package.name = maverickskills
package.domain = dev.maverick
version = 0.1.6

source.dir = .
source.include_exts = py

# Pure-Python only: the skill module imports nothing but stdlib, so no
# native recipes are needed beyond Kivy itself.
requirements = python3,kivy

orientation = portrait
fullscreen = 0

# No permissions: the bundled skill is offline. Add INTERNET only when a
# relay-backed skill lands (see ../README.md "Hard limits").
android.permissions =

android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
