#include "myui_rga.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if defined(__has_include)
#  if __has_include(<im2d.h>)
#    include <im2d.h>
#  elif __has_include("im2d.h")
#    include "im2d.h"
#  else
#    error "Rockchip RGA im2d.h not found. Install/copy the librga development headers before building libmyui_rga.so."
#  endif
#else
#  include <im2d.h>
#endif

#if defined(__has_include)
#  if __has_include(<RgaUtils.h>)
#    include <RgaUtils.h>
#  elif __has_include("RgaUtils.h")
#    include "RgaUtils.h"
#  endif
#endif

static char g_last_error[2048] = "not initialized";

static void set_error(const char *msg) {
    if (!msg) {
        msg = "unknown";
    }
    snprintf(g_last_error, sizeof(g_last_error), "%s", msg);
}

static const char *status_name(int status) {
    switch ((IM_STATUS)status) {
    case IM_STATUS_NOERROR:
        return "NOERROR";
    case IM_STATUS_SUCCESS:
        return "SUCCESS";
    case IM_STATUS_NOT_SUPPORTED:
        return "NOT_SUPPORTED";
    case IM_STATUS_OUT_OF_MEMORY:
        return "OUT_OF_MEMORY";
    case IM_STATUS_INVALID_PARAM:
        return "INVALID_PARAM";
    case IM_STATUS_ILLEGAL_PARAM:
        return "ILLEGAL_PARAM";
    case IM_STATUS_ERROR_VERSION:
        return "ERROR_VERSION";
    case IM_STATUS_FAILED:
        return "FAILED";
    default:
        return "UNKNOWN";
    }
}

static const char *format_name(int format) {
    switch (format) {
    case RK_FORMAT_YCbCr_420_SP:
        return "NV12";
    case RK_FORMAT_BGR_888:
        return "BGR888";
    case RK_FORMAT_BGRX_8888:
        return "BGRX8888";
    default:
        return "UNKNOWN";
    }
}

static const char *rotate_name(int rotate_code) {
    switch (rotate_code) {
    case 0:
        return "none";
    case 1:
        return "ccw90";
    case 2:
        return "cw90";
    case 3:
        return "180";
    default:
        return "unknown";
    }
}

static void set_im2d_error_detail(
    const char *op,
    int status,
    const rga_buffer_t *src,
    const rga_buffer_t *dst,
    int rotate_code,
    int usage,
    size_t src_bytes,
    size_t dst_bytes,
    const char *extra
) {
    const char *status_text = imStrError_t((IM_STATUS)status);
    snprintf(
        g_last_error,
        sizeof(g_last_error),
        "%s failed: im2d_status=%d(%s) im2d_error=%s "
        "src=%dx%d stride=%dx%d fmt=%s(0x%x) bytes=%zu "
        "dst=%dx%d stride=%dx%d fmt=%s(0x%x) bytes=%zu "
        "rotate=%s(%d) usage=0x%x%s%s",
        op,
        status,
        status_name(status),
        status_text ? status_text : "",
        src ? src->width : 0,
        src ? src->height : 0,
        src ? src->wstride : 0,
        src ? src->hstride : 0,
        src ? format_name(src->format) : "UNKNOWN",
        src ? src->format : 0,
        src_bytes,
        dst ? dst->width : 0,
        dst ? dst->height : 0,
        dst ? dst->wstride : 0,
        dst ? dst->hstride : 0,
        dst ? format_name(dst->format) : "UNKNOWN",
        dst ? dst->format : 0,
        dst_bytes,
        rotate_name(rotate_code),
        rotate_code,
        usage,
        extra ? " " : "",
        extra ? extra : ""
    );
}

const char *myui_rga_last_error(void) {
    return g_last_error;
}

const char *myui_rga_version(void) {
    return "myui_rga/1.2 rotate-diagnostics";
}

int myui_rga_available(void) {
    if (access("/dev/rga", R_OK | W_OK) != 0 && access("/dev/rga", R_OK) != 0) {
        snprintf(g_last_error, sizeof(g_last_error), "/dev/rga not accessible: errno=%d", errno);
        return 0;
    }
    set_error("ok");
    return 1;
}

static int rotation_to_im_usage(int rotate_code, int *usage) {
    if (!usage) {
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    switch (rotate_code) {
    case 0:
        *usage = 0;
        return MYUI_RGA_OK;
    case 1: /* ccw90 == RGA 270 degrees clockwise */
        *usage = IM_HAL_TRANSFORM_ROT_270;
        return MYUI_RGA_OK;
    case 2: /* cw90 */
        *usage = IM_HAL_TRANSFORM_ROT_90;
        return MYUI_RGA_OK;
    case 3:
        *usage = IM_HAL_TRANSFORM_ROT_180;
        return MYUI_RGA_OK;
    default:
        set_error("unsupported rotate_code");
        return MYUI_RGA_ERR_UNSUPPORTED;
    }
}

static int validate_dims(int src_w, int src_h, int dst_w, int dst_h, int rotate_code) {
    if (src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0) {
        set_error("width/height must be positive");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if ((src_w & 1) || (src_h & 1)) {
        set_error("NV12 width/height must be even");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if ((size_t)src_w > SIZE_MAX / (size_t)src_h / 3u) {
        set_error("source dimensions overflow temporary BGR buffer size");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if (rotate_code == 1 || rotate_code == 2) {
        if (!(dst_w == src_h && dst_h == src_w)) {
            set_error("first wrapper version supports 90-degree rotate only without resize");
            return MYUI_RGA_ERR_UNSUPPORTED;
        }
    } else if (rotate_code == 3) {
        if (!(dst_w == src_w && dst_h == src_h)) {
            set_error("first wrapper version supports 180-degree rotate only without resize");
            return MYUI_RGA_ERR_UNSUPPORTED;
        }
    }
    return MYUI_RGA_OK;
}

static int validate_bgr_rotate_dims(int src_w, int src_h, int dst_w, int dst_h, int rotate_code) {
    if (src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0) {
        set_error("width/height must be positive");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if (rotate_code == 0 || rotate_code == 3) {
        if (!(dst_w == src_w && dst_h == src_h)) {
            set_error("BGR rotate 0/180 requires dst dimensions equal to src dimensions");
            return MYUI_RGA_ERR_UNSUPPORTED;
        }
    } else if (rotate_code == 1 || rotate_code == 2) {
        if (!(dst_w == src_h && dst_h == src_w)) {
            set_error("BGR rotate 90/270 requires swapped dst dimensions");
            return MYUI_RGA_ERR_UNSUPPORTED;
        }
    } else {
        set_error("unsupported rotate_code");
        return MYUI_RGA_ERR_UNSUPPORTED;
    }
    return MYUI_RGA_OK;
}

static size_t bpp_for_format(int format) {
    if (format == RK_FORMAT_BGR_888 || format == RK_FORMAT_RGB_888) {
        return 3u;
    }
    if (format == RK_FORMAT_BGRX_8888 || format == RK_FORMAT_BGRA_8888 ||
        format == RK_FORMAT_RGBX_8888 || format == RK_FORMAT_RGBA_8888) {
        return 4u;
    }
    if (format == RK_FORMAT_YCbCr_420_SP) {
        return 0u;
    }
    return 0u;
}

static size_t buffer_size_bytes(int width, int height, int format) {
    if (width <= 0 || height <= 0) {
        return 0u;
    }
    if (format == RK_FORMAT_YCbCr_420_SP) {
        return (size_t)width * (size_t)height * 3u / 2u;
    }
    return (size_t)width * (size_t)height * bpp_for_format(format);
}

static im_rect make_rect(int w, int h) {
    im_rect rect;
    memset(&rect, 0, sizeof(rect));
    rect.x = 0;
    rect.y = 0;
    rect.width = w;
    rect.height = h;
    return rect;
}

static int im_status_to_ret_detail(
    const char *op,
    IM_STATUS status,
    const rga_buffer_t *src,
    const rga_buffer_t *dst,
    int rotate_code,
    int usage,
    size_t src_bytes,
    size_t dst_bytes,
    const char *extra
) {
    if (status == IM_STATUS_SUCCESS || status == IM_STATUS_NOERROR) {
        return MYUI_RGA_OK;
    }
    set_im2d_error_detail(op, (int)status, src, dst, rotate_code, usage, src_bytes, dst_bytes, extra);
    return MYUI_RGA_ERR_IM2D + (int)status;
}

int myui_rga_nv12_to_bgr(
    const unsigned char *src_nv12,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
) {
    if (!src_nv12 || !dst_bgr) {
        set_error("src_nv12/dst_bgr pointer is null");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if (!myui_rga_available()) {
        return MYUI_RGA_ERR_NO_DEVICE;
    }

    int usage = 0;
    int ret = rotation_to_im_usage(rotate_code, &usage);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }
    ret = validate_dims(src_w, src_h, dst_w, dst_h, rotate_code);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }

    rga_buffer_t src = wrapbuffer_virtualaddr_t((void *)src_nv12, src_w, src_h, src_w, src_h, RK_FORMAT_YCbCr_420_SP);
    rga_buffer_t dst = wrapbuffer_virtualaddr_t((void *)dst_bgr, dst_w, dst_h, dst_w, dst_h, RK_FORMAT_BGR_888);
    size_t src_bytes = buffer_size_bytes(src_w, src_h, RK_FORMAT_YCbCr_420_SP);
    size_t dst_bytes = buffer_size_bytes(dst_w, dst_h, RK_FORMAT_BGR_888);

    if (rotate_code == 0 && src_w == dst_w && src_h == dst_h) {
        IM_STATUS status = imcvtcolor_t(src, dst, RK_FORMAT_YCbCr_420_SP, RK_FORMAT_BGR_888, IM_COLOR_SPACE_DEFAULT, 1);
        ret = im_status_to_ret_detail("imcvtcolor", status, &src, &dst, rotate_code, usage, src_bytes, dst_bytes, NULL);
        if (ret == MYUI_RGA_OK) {
            set_error("ok: nv12_to_bgr");
        }
        return ret;
    }

    size_t tmp_size = (size_t)src_w * (size_t)src_h * 3u;
    unsigned char *tmp_bgr = (unsigned char *)malloc(tmp_size);
    if (!tmp_bgr) {
        set_error("malloc tmp_bgr failed");
        return MYUI_RGA_ERR_ALLOC;
    }

    rga_buffer_t tmp = wrapbuffer_virtualaddr_t((void *)tmp_bgr, src_w, src_h, src_w, src_h, RK_FORMAT_BGR_888);
    IM_STATUS status = imcvtcolor_t(src, tmp, RK_FORMAT_YCbCr_420_SP, RK_FORMAT_BGR_888, IM_COLOR_SPACE_DEFAULT, 1);
    size_t tmp_bytes = buffer_size_bytes(src_w, src_h, RK_FORMAT_BGR_888);
    ret = im_status_to_ret_detail("imcvtcolor(tmp)", status, &src, &tmp, rotate_code, usage, src_bytes, tmp_bytes, NULL);
    if (ret != MYUI_RGA_OK) {
        free(tmp_bgr);
        return ret;
    }

    int used_bgrx_rotate = 0;
    if (rotate_code == 0) {
        status = imresize_t(tmp, dst, 0, 0, INTER_LINEAR, 1);
        ret = im_status_to_ret_detail("imresize", status, &tmp, &dst, rotate_code, usage, tmp_bytes, dst_bytes, NULL);
    } else {
        im_rect src_rect = make_rect(src_w, src_h);
        im_rect dst_rect = make_rect(dst_w, dst_h);
        rga_buffer_t pat;
        im_rect pat_rect;
        memset(&pat, 0, sizeof(pat));
        memset(&pat_rect, 0, sizeof(pat_rect));
        IM_STATUS check_status = imcheck_t(tmp, dst, pat, src_rect, dst_rect, pat_rect, usage);
        if (check_status != IM_STATUS_SUCCESS && check_status != IM_STATUS_NOERROR) {
            ret = im_status_to_ret_detail("imcheck(imrotate BGR888)", check_status, &tmp, &dst, rotate_code, usage, tmp_bytes, dst_bytes, NULL);
            free(tmp_bgr);
            return ret;
        }
        status = imrotate_t(tmp, dst, usage, 1);
        ret = im_status_to_ret_detail("imrotate(BGR888)", status, &tmp, &dst, rotate_code, usage, tmp_bytes, dst_bytes, NULL);
        if (ret != MYUI_RGA_OK) {
            int alt_ret = myui_rga_bgrx_rotate_to_bgr(tmp_bgr, src_w, src_h, dst_bgr, dst_w, dst_h, rotate_code);
            if (alt_ret == MYUI_RGA_OK) {
                set_error("ok: nv12_to_bgr_transform via bgrx_rotate_to_bgr");
                ret = MYUI_RGA_OK;
                used_bgrx_rotate = 1;
            }
        }
    }
    free(tmp_bgr);
    if (ret == MYUI_RGA_OK) {
        if (used_bgrx_rotate) {
            set_error("ok: nv12_to_bgr_transform via bgrx_rotate_to_bgr");
        } else {
            set_error("ok: nv12_to_bgr_transform");
        }
    }
    return ret;
}

int myui_rga_bgr_rotate(
    const unsigned char *src_bgr,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
) {
    if (!src_bgr || !dst_bgr) {
        set_error("src_bgr/dst_bgr pointer is null");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if (!myui_rga_available()) {
        return MYUI_RGA_ERR_NO_DEVICE;
    }
    int usage = 0;
    int ret = rotation_to_im_usage(rotate_code, &usage);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }
    ret = validate_bgr_rotate_dims(src_w, src_h, dst_w, dst_h, rotate_code);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }
    rga_buffer_t src = wrapbuffer_virtualaddr_t((void *)src_bgr, src_w, src_h, src_w, src_h, RK_FORMAT_BGR_888);
    rga_buffer_t dst = wrapbuffer_virtualaddr_t((void *)dst_bgr, dst_w, dst_h, dst_w, dst_h, RK_FORMAT_BGR_888);
    size_t src_bytes = buffer_size_bytes(src_w, src_h, RK_FORMAT_BGR_888);
    size_t dst_bytes = buffer_size_bytes(dst_w, dst_h, RK_FORMAT_BGR_888);
    if (rotate_code == 0) {
        IM_STATUS copy_status = imcopy_t(src, dst, 1);
        ret = im_status_to_ret_detail("imcopy(BGR888)", copy_status, &src, &dst, rotate_code, usage, src_bytes, dst_bytes, NULL);
    } else {
        im_rect src_rect = make_rect(src_w, src_h);
        im_rect dst_rect = make_rect(dst_w, dst_h);
        rga_buffer_t pat;
        im_rect pat_rect;
        memset(&pat, 0, sizeof(pat));
        memset(&pat_rect, 0, sizeof(pat_rect));
        IM_STATUS check_status = imcheck_t(src, dst, pat, src_rect, dst_rect, pat_rect, usage);
        if (check_status != IM_STATUS_SUCCESS && check_status != IM_STATUS_NOERROR) {
            return im_status_to_ret_detail("imcheck(imrotate BGR888 diag)", check_status, &src, &dst, rotate_code, usage, src_bytes, dst_bytes, NULL);
        }
        IM_STATUS rotate_status = imrotate_t(src, dst, usage, 1);
        ret = im_status_to_ret_detail("imrotate(BGR888 diag)", rotate_status, &src, &dst, rotate_code, usage, src_bytes, dst_bytes, NULL);
    }
    if (ret == MYUI_RGA_OK) {
        set_error("ok: bgr_rotate");
    }
    return ret;
}

int myui_rga_bgr_rotate_strided(
    const unsigned char *src_bgr,
    int src_w,
    int src_h,
    int src_wstride,
    int src_hstride,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int dst_wstride,
    int dst_hstride,
    int rotate_code
) {
    if (!src_bgr || !dst_bgr) {
        set_error("src_bgr/dst_bgr pointer is null");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if (!myui_rga_available()) {
        return MYUI_RGA_ERR_NO_DEVICE;
    }
    if (src_wstride < src_w || src_hstride < src_h || dst_wstride < dst_w || dst_hstride < dst_h) {
        set_error("stride must be greater than or equal to active dimensions");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    int usage = 0;
    int ret = rotation_to_im_usage(rotate_code, &usage);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }
    ret = validate_bgr_rotate_dims(src_w, src_h, dst_w, dst_h, rotate_code);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }
    rga_buffer_t src = wrapbuffer_virtualaddr_t((void *)src_bgr, src_w, src_h, src_wstride, src_hstride, RK_FORMAT_BGR_888);
    rga_buffer_t dst = wrapbuffer_virtualaddr_t((void *)dst_bgr, dst_w, dst_h, dst_wstride, dst_hstride, RK_FORMAT_BGR_888);
    size_t src_bytes = buffer_size_bytes(src_wstride, src_hstride, RK_FORMAT_BGR_888);
    size_t dst_bytes = buffer_size_bytes(dst_wstride, dst_hstride, RK_FORMAT_BGR_888);
    im_rect src_rect = make_rect(src_w, src_h);
    im_rect dst_rect = make_rect(dst_w, dst_h);
    rga_buffer_t pat;
    im_rect pat_rect;
    memset(&pat, 0, sizeof(pat));
    memset(&pat_rect, 0, sizeof(pat_rect));
    IM_STATUS check_status = imcheck_t(src, dst, pat, src_rect, dst_rect, pat_rect, usage);
    if (check_status != IM_STATUS_SUCCESS && check_status != IM_STATUS_NOERROR) {
        return im_status_to_ret_detail("imcheck(imrotate BGR888 strided)", check_status, &src, &dst, rotate_code, usage, src_bytes, dst_bytes, NULL);
    }
    IM_STATUS rotate_status = rotate_code == 0 ? imcopy_t(src, dst, 1) : imrotate_t(src, dst, usage, 1);
    ret = im_status_to_ret_detail("imrotate(BGR888 strided)", rotate_status, &src, &dst, rotate_code, usage, src_bytes, dst_bytes, NULL);
    if (ret == MYUI_RGA_OK) {
        set_error("ok: bgr_rotate_strided");
    }
    return ret;
}

int myui_rga_bgrx_rotate_to_bgr(
    const unsigned char *src_bgr,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
) {
    if (!src_bgr || !dst_bgr) {
        set_error("src_bgr/dst_bgr pointer is null");
        return MYUI_RGA_ERR_BAD_ARGUMENT;
    }
    if (!myui_rga_available()) {
        return MYUI_RGA_ERR_NO_DEVICE;
    }
    int usage = 0;
    int ret = rotation_to_im_usage(rotate_code, &usage);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }
    ret = validate_bgr_rotate_dims(src_w, src_h, dst_w, dst_h, rotate_code);
    if (ret != MYUI_RGA_OK) {
        return ret;
    }

    size_t src_bgrx_bytes = buffer_size_bytes(src_w, src_h, RK_FORMAT_BGRX_8888);
    size_t dst_bgrx_bytes = buffer_size_bytes(dst_w, dst_h, RK_FORMAT_BGRX_8888);
    unsigned char *tmp_bgrx = (unsigned char *)malloc(src_bgrx_bytes);
    unsigned char *rot_bgrx = (unsigned char *)malloc(dst_bgrx_bytes);
    if (!tmp_bgrx || !rot_bgrx) {
        free(tmp_bgrx);
        free(rot_bgrx);
        set_error("malloc bgrx staging buffer failed");
        return MYUI_RGA_ERR_ALLOC;
    }

    rga_buffer_t src = wrapbuffer_virtualaddr_t((void *)src_bgr, src_w, src_h, src_w, src_h, RK_FORMAT_BGR_888);
    rga_buffer_t tmp = wrapbuffer_virtualaddr_t((void *)tmp_bgrx, src_w, src_h, src_w, src_h, RK_FORMAT_BGRX_8888);
    rga_buffer_t rot = wrapbuffer_virtualaddr_t((void *)rot_bgrx, dst_w, dst_h, dst_w, dst_h, RK_FORMAT_BGRX_8888);
    rga_buffer_t dst = wrapbuffer_virtualaddr_t((void *)dst_bgr, dst_w, dst_h, dst_w, dst_h, RK_FORMAT_BGR_888);

    size_t src_bytes = buffer_size_bytes(src_w, src_h, RK_FORMAT_BGR_888);
    size_t dst_bytes = buffer_size_bytes(dst_w, dst_h, RK_FORMAT_BGR_888);
    IM_STATUS status = imcvtcolor_t(src, tmp, RK_FORMAT_BGR_888, RK_FORMAT_BGRX_8888, IM_COLOR_SPACE_DEFAULT, 1);
    ret = im_status_to_ret_detail("imcvtcolor(BGR888->BGRX8888)", status, &src, &tmp, rotate_code, usage, src_bytes, src_bgrx_bytes, NULL);
    if (ret != MYUI_RGA_OK) {
        free(tmp_bgrx);
        free(rot_bgrx);
        return ret;
    }

    if (rotate_code == 0) {
        status = imcopy_t(tmp, rot, 1);
        ret = im_status_to_ret_detail("imcopy(BGRX8888)", status, &tmp, &rot, rotate_code, usage, src_bgrx_bytes, dst_bgrx_bytes, NULL);
    } else {
        im_rect src_rect = make_rect(src_w, src_h);
        im_rect dst_rect = make_rect(dst_w, dst_h);
        rga_buffer_t pat;
        im_rect pat_rect;
        memset(&pat, 0, sizeof(pat));
        memset(&pat_rect, 0, sizeof(pat_rect));
        IM_STATUS check_status = imcheck_t(tmp, rot, pat, src_rect, dst_rect, pat_rect, usage);
        if (check_status != IM_STATUS_SUCCESS && check_status != IM_STATUS_NOERROR) {
            ret = im_status_to_ret_detail("imcheck(imrotate BGRX8888)", check_status, &tmp, &rot, rotate_code, usage, src_bgrx_bytes, dst_bgrx_bytes, NULL);
            free(tmp_bgrx);
            free(rot_bgrx);
            return ret;
        }
        status = imrotate_t(tmp, rot, usage, 1);
        ret = im_status_to_ret_detail("imrotate(BGRX8888)", status, &tmp, &rot, rotate_code, usage, src_bgrx_bytes, dst_bgrx_bytes, NULL);
    }
    if (ret != MYUI_RGA_OK) {
        free(tmp_bgrx);
        free(rot_bgrx);
        return ret;
    }

    status = imcvtcolor_t(rot, dst, RK_FORMAT_BGRX_8888, RK_FORMAT_BGR_888, IM_COLOR_SPACE_DEFAULT, 1);
    ret = im_status_to_ret_detail("imcvtcolor(BGRX8888->BGR888)", status, &rot, &dst, rotate_code, usage, dst_bgrx_bytes, dst_bytes, NULL);
    free(tmp_bgrx);
    free(rot_bgrx);
    if (ret == MYUI_RGA_OK) {
        set_error("ok: bgrx_rotate_to_bgr");
    }
    return ret;
}
