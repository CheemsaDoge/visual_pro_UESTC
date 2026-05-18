#ifndef MYUI_RGA_H
#define MYUI_RGA_H

#ifdef __cplusplus
extern "C" {
#endif

#define MYUI_RGA_OK 0
#define MYUI_RGA_ERR_BAD_ARGUMENT -1
#define MYUI_RGA_ERR_UNSUPPORTED -2
#define MYUI_RGA_ERR_NO_DEVICE -3
#define MYUI_RGA_ERR_ALLOC -4
#define MYUI_RGA_ERR_IM2D -1000

/* rotate_code values shared with Python:
 *   0 = none
 *   1 = ccw90
 *   2 = cw90
 *   3 = 180
 */
int myui_rga_available(void);

int myui_rga_nv12_to_bgr(
    const unsigned char *src_nv12,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
);

int myui_rga_bgr_rotate(
    const unsigned char *src_bgr,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
);

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
);

int myui_rga_bgrx_rotate_to_bgr(
    const unsigned char *src_bgr,
    int src_w,
    int src_h,
    unsigned char *dst_bgr,
    int dst_w,
    int dst_h,
    int rotate_code
);

const char *myui_rga_last_error(void);
const char *myui_rga_version(void);

#ifdef __cplusplus
}
#endif

#endif /* MYUI_RGA_H */
