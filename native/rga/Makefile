# Minimal RK3588 RGA wrapper for the Python GUI.
# Build on the target board or with an aarch64 toolchain that has librga headers.
#
# Cross build example:
#   make CXX=aarch64-buildroot-linux-gnu-g++ \
#        SYSROOT=/path/to/sysroot \
#        RGA_INCLUDE_DIR=/path/to/librga/include \
#        RGA_LIB_DIR=/path/to/librga/lib

CXX ?= g++
PYTHON ?= python3
TARGET ?= libmyui_rga.so
SRCS := myui_rga.cpp
HDRS := myui_rga.h

SYSROOT ?=
RGA_INCLUDE_DIR ?=
RGA_LIB_DIR ?=

SYSROOT_FLAG := $(if $(strip $(SYSROOT)),--sysroot=$(SYSROOT),)
RGA_CFLAGS ?= $(if $(strip $(RGA_INCLUDE_DIR)),-I$(RGA_INCLUDE_DIR),)
RGA_LDFLAGS ?= $(if $(strip $(RGA_LIB_DIR)),-L$(RGA_LIB_DIR),) -lrga
CXXFLAGS ?= -O2 -Wall -Wextra
CXX_CMD := $(firstword $(CXX))

.PHONY: all clean probe check-dev test-load

all: $(TARGET)

check-dev:
	@command -v $(CXX_CMD) >/dev/null 2>&1 || { echo "error: C++ compiler '$(CXX_CMD)' not found" >&2; exit 2; }
	@echo "[build config] CXX=$(CXX)"
	@echo "[build config] SYSROOT=$(SYSROOT)"
	@echo "[build config] RGA_INCLUDE_DIR=$(RGA_INCLUDE_DIR)"
	@echo "[build config] RGA_LIB_DIR=$(RGA_LIB_DIR)"
	@printf '#include <im2d.h>\n' | $(CXX) $(SYSROOT_FLAG) $(RGA_CFLAGS) -x c++ -E - >/dev/null 2>&1 || { echo "error: im2d.h not found; set SYSROOT or RGA_INCLUDE_DIR to Rockchip librga development headers" >&2; exit 3; }

$(TARGET): $(SRCS) $(HDRS) | check-dev
	$(CXX) $(SYSROOT_FLAG) $(CXXFLAGS) -fPIC -shared $(RGA_CFLAGS) -o $@ $(SRCS) $(RGA_LDFLAGS)

probe:
	@echo "[build env]"
	@echo "CXX=$(CXX)"
	@echo "SYSROOT=$(SYSROOT)"
	@echo "RGA_INCLUDE_DIR=$(RGA_INCLUDE_DIR)"
	@echo "RGA_LIB_DIR=$(RGA_LIB_DIR)"
	@echo "[devices/libs]"
	@ls -l /dev/rga* /usr/lib*/librga.so* /usr/local/lib*/librga.so* /lib*/librga.so* 2>/dev/null || true
	@echo "[headers]"
	@if [ -n "$(RGA_INCLUDE_DIR)" ]; then find "$(RGA_INCLUDE_DIR)" -iname '*rga*' -o -iname 'im2d.h' -o -iname 'RgaApi.h' 2>/dev/null; fi
	@if [ -n "$(SYSROOT)" ]; then find "$(SYSROOT)/usr/include" "$(SYSROOT)/usr/local/include" -iname '*rga*' -o -iname 'im2d.h' -o -iname 'RgaApi.h' 2>/dev/null; fi
	@find /usr/include /usr/local/include -iname '*rga*' -o -iname 'im2d.h' -o -iname 'RgaApi.h' 2>/dev/null | sort || true
	@echo "[compiler]"
	@command -v $(CXX_CMD) || true

# Validates that ctypes can load the built wrapper and call myui_rga_available().
test-load:
	@test -f $(TARGET) || { echo "error: $(TARGET) not found; build or deploy it first" >&2; exit 4; }
	$(PYTHON) -c "import ctypes; ctypes.CDLL('librga.so', mode=getattr(ctypes, 'RTLD_GLOBAL', 0)); lib=ctypes.CDLL('./libmyui_rga.so'); lib.myui_rga_available.restype=ctypes.c_int; print('myui_rga_available=', lib.myui_rga_available())"

clean:
	rm -f $(TARGET) *.o
