
import math
import tensorflow as tf
from utils import filters

def reconstruct_w_level2(w):
    w_rec = [[[[],[]] for x in range(2)] for i in range(2+1)]

    ws01 = tf.split(tf.split(w, 2, axis=1)[0], 2, axis=2)
    ws02 = tf.split(tf.split(w, 2, axis=1)[1], 2, axis=2)
    w_split = [ws01] + [ws02]

    for m in range(2):
        for n in range(2):
            ws11 = tf.split(tf.split(w_split[m][n], 2, axis=1)[0], 2, axis=2)
            ws12 = tf.split(tf.split(w_split[m][n], 2, axis=1)[1], 2, axis=2)
            w_rec[0][m][n] = [ws11[1]] + ws12
            ll_lh = tf.split(tf.split(ws11[0], 2, axis=1)[0], 2, axis=2)
            hl_hh = tf.split(tf.split(ws11[0], 2, axis=1)[1], 2, axis=2)
            ll = ll_lh[0]
            lh_hl_ll = [ll_lh[1]] + hl_hh
            w_rec[1][m][n] = lh_hl_ll
            w_rec[2][m][n] = ll

    return w_rec


def roll_pad(data, pad_len):

    # circular shift
    # This procedure (periodic extension) can create
    # undesirable artifacts at the beginning and end
    # of the subband signals, however, it is the most
    # convenient solution.
    # When the analysis and synthesis filters are exactly symmetric,
    # a different procedure (symmetric extension) can be used,
    # that avoids the artifacts associated with periodic extension

    data_roll = tf.roll(data, shift=-pad_len, axis=1)
    # zero padding

    data_roll_pad = tf.pad(data_roll,
                           [[0, 0], [pad_len, pad_len], [0, 0], [0, 0]],
                           mode='CONSTANT',
                           constant_values=0)

    return data_roll_pad


def fir_down_sample(data, fir, start=0, step=2):
    # input tensors rank 4

    data_tr = tf.transpose(data, perm=[0, 2, 1, 3])
    conv = tf.nn.conv2d(
        data_tr, fir, padding='SAME', strides=[1, 1, 1, 1],
    )
    conv_tr = tf.transpose(conv, perm=[0, 2, 1, 3])

    # down sample
    lo_conv_ds = conv_tr[:, start:conv_tr.shape[1]:step, :, :]
    return lo_conv_ds


def circular_shift_fix_crop(data, shift_fix, crop):

    circular_shift_fix = tf.math.add(data[:, 0:shift_fix, :, :],
                                     data[:, -shift_fix:, :, :])

    fix = tf.concat([circular_shift_fix, data[:, shift_fix:, :, :]], axis=1)

    if crop == 0:
        res = fix
    else:
        res = fix[:, 0:crop, :, :]

    return res


def list_to_tf(data):
    list_len = len(data)
    data_tf = tf.constant(data)
    data_tf = tf.reshape(data_tf, (1, list_len, 1, 1))
    return data_tf


def duel_filter_tf(duelfilt):
    filt_len = len(duelfilt[0][0])

    tree1_lp_tf = list_to_tf(duelfilt[0][0])
    tree1_hp_tf = list_to_tf(duelfilt[0][1])
    tree2_lp_tf = list_to_tf(duelfilt[1][0])
    tree2_hp_tf = list_to_tf(duelfilt[1][1])

    tree1 = tf.stack((tree1_lp_tf, tree1_hp_tf), axis=0)
    tree2 = tf.stack((tree2_lp_tf, tree2_hp_tf), axis=0)
    duelfilt_tf = tf.stack((tree1, tree2), axis=0)
    return duelfilt_tf


def construct_tf_filter(lod_row, hid_row, lod_col, hid_col):

    filt_len = len(lod_row)

    lod_row_tf = tf.constant(lod_row[::-1])
    lod_row_tf = tf.reshape(lod_row_tf, (1, filt_len, 1, 1))

    hid_row_tf = tf.constant(hid_row[::-1])
    hid_row_tf = tf.reshape(hid_row_tf, (1, filt_len, 1, 1))

    lod_col_tf = tf.constant(lod_col[::-1])
    lod_col_tf = tf.reshape(lod_col_tf, (1, filt_len, 1, 1))

    hid_col_tf = tf.constant(hid_col[::-1])
    hid_col_tf = tf.reshape(hid_col_tf, (1, filt_len, 1, 1))

    return lod_row_tf, hid_row_tf, lod_col_tf, hid_col_tf


def add_sub(a, b):
    add = (a + b) / math.sqrt(2)
    sub = (a - b) / math.sqrt(2)
    return add, sub


def up_sample_fir(x, fir):
    # create zero like tensor
    x = tf.transpose(x, perm=[0, 2, 1, 3])
    zero_tensor = tf.zeros_like(x)
    # stack both tensors
    stack_rows = tf.stack([x, zero_tensor], axis=3)
    # reshape for zero insertion between the rows
    stack_rows = tf.reshape(stack_rows, shape=[-1, x.shape[1], x.shape[2]*2, x.shape[3]])

    conv = tf.nn.conv2d(
        stack_rows, fir, padding='SAME', strides=[1, 1, 1, 1],
    )
    res = tf.transpose(conv, perm=[0, 2, 1, 3])
    return res


def over_sample_rows(x):
    # create zero like tensor
    x = tf.transpose(x, perm=[0, 2, 1, 3])
    x_sqrt = x*(1/math.sqrt(2))
    # stack both tensors
    stack_rows = tf.stack([x, x_sqrt], axis=3)
    # reshape for zero insertion between the rows
    stack_rows = tf.reshape(stack_rows, shape=[-1, x.shape[1], x.shape[2]*2, x.shape[3]])

    res = tf.transpose(stack_rows, perm=[0, 2, 1, 3])
    return res


def analysis_filter_bank2d(x, lod_row, hid_row, lod_col, hid_col):
    # parameters
    h = int(x.shape[1])
    w = int(x.shape[2])
    filt_len = int(lod_row.shape[1])
    x_roll_padd = roll_pad(x, filt_len//2)

    lo_conv_ds = fir_down_sample(x_roll_padd, lod_row)
    hi_conv_ds = fir_down_sample(x_roll_padd, hid_row)

    # # crop to needed dims
    lo = circular_shift_fix_crop(lo_conv_ds, filt_len//2, h//2)
    hi = circular_shift_fix_crop(hi_conv_ds, filt_len//2, h//2)

    # next is the columns filtering
    lo_tr = tf.transpose(lo, perm=[0, 2, 1, 3])
    hi_tr = tf.transpose(hi, perm=[0, 2, 1, 3])

    lo_tr_roll_padd = roll_pad(lo_tr, filt_len//2)
    hi_tr_roll_padd = roll_pad(hi_tr, filt_len//2)

    lo_lo_conv_ds = fir_down_sample(lo_tr_roll_padd, lod_col)
    lo_hi_conv_ds = fir_down_sample(lo_tr_roll_padd, hid_col)
    hi_lo_conv_ds = fir_down_sample(hi_tr_roll_padd, lod_col)
    hi_hi_conv_ds = fir_down_sample(hi_tr_roll_padd, hid_col)

    lo_lo = circular_shift_fix_crop(lo_lo_conv_ds, filt_len//2, w//2)
    lo_hi = circular_shift_fix_crop(lo_hi_conv_ds, filt_len//2, w//2)
    hi_lo = circular_shift_fix_crop(hi_lo_conv_ds, filt_len//2, w//2)
    hi_hi = circular_shift_fix_crop(hi_hi_conv_ds, filt_len//2, w//2)

    lo_lo = tf.transpose(lo_lo, perm=[0, 2, 1, 3])
    lo_hi = tf.transpose(lo_hi, perm=[0, 2, 1, 3])
    hi_lo = tf.transpose(hi_lo, perm=[0, 2, 1, 3])
    hi_hi = tf.transpose(hi_hi, perm=[0, 2, 1, 3])

    return [lo_lo, [lo_hi, hi_lo, hi_hi]]


def synthesis_filter_bank2d(ca, cd, lor_row, hir_row, lor_col, hir_col):

    h = int(ca.shape[1])
    w = int(ca.shape[2])
    filt_len = int(lor_row.shape[1])

    ll = tf.transpose(ca, perm=[0,2,1,3])
    lh = tf.transpose(cd[0], perm=[0,2,1,3])
    hl = tf.transpose(cd[1], perm=[0,2,1,3])
    hh = tf.transpose(cd[2], perm=[0,2,1,3])

    ll_pad = tf.pad(ll,
                    [[0, 0], [filt_len//2, filt_len//2], [0, 0], [0, 0]],
                    mode='CONSTANT',
                    constant_values=0)

    lh_pad = tf.pad(lh,
                    [[0, 0], [filt_len//2, filt_len//2], [0, 0], [0, 0]],
                    mode='CONSTANT',
                    constant_values=0)

    hl_pad = tf.pad(hl,
                    [[0, 0], [filt_len//2, filt_len//2], [0, 0], [0, 0]],
                    mode='CONSTANT',
                    constant_values=0)

    hh_pad = tf.pad(hh,
                    [[0, 0], [filt_len//2, filt_len//2], [0, 0], [0, 0]],
                    mode='CONSTANT',
                    constant_values=0)

    ll_conv = up_sample_fir(ll_pad, lor_col)
    lh_conv = up_sample_fir(lh_pad, hir_col)
    hl_conv = up_sample_fir(hl_pad, lor_col)
    hh_conv = up_sample_fir(hh_pad, hir_col)

    ll_lh_add = tf.math.add(ll_conv, lh_conv)
    hl_hh_add = tf.math.add(hl_conv, hh_conv)

    ll_lh_crop = ll_lh_add[:, filt_len//2:-filt_len//2-2, :, :]
    hl_hh_crop = hl_hh_add[:, filt_len//2:-filt_len//2-2, :, :]

    ll_lh_fix_crop = circular_shift_fix_crop(ll_lh_crop, filt_len-2, 2*w)
    hl_hh_fix_crop = circular_shift_fix_crop(hl_hh_crop, filt_len-2, 2*w)

    ll_lh_fix_crop_roll = tf.roll(ll_lh_fix_crop, shift=1-filt_len//2, axis=1)
    hl_hh_fix_crop_roll = tf.roll(hl_hh_fix_crop, shift=1-filt_len//2, axis=1)

    ll_lh = tf.transpose(ll_lh_fix_crop_roll, perm=[0, 2, 1, 3])
    hl_hh = tf.transpose(hl_hh_fix_crop_roll, perm=[0, 2, 1, 3])

    ll_lh_pad = tf.pad(ll_lh,
                       [[0, 0], [filt_len//2, filt_len//2], [0, 0], [0, 0]],
                       mode='CONSTANT',
                       constant_values=0)

    hl_hh_pad = tf.pad(hl_hh,
                       [[0, 0], [filt_len//2, filt_len//2], [0, 0], [0, 0]],
                       mode='CONSTANT',
                       constant_values=0)

    ll_lh_conv = up_sample_fir(ll_lh_pad, lor_row)
    hl_hh_conv = up_sample_fir(hl_hh_pad, hir_row)

    ll_lh_hl_hh_add = tf.math.add(ll_lh_conv,hl_hh_conv)
    ll_lh_hl_hh_add_crop = ll_lh_hl_hh_add[:, filt_len//2:-filt_len//2-2, :, :]

    y = circular_shift_fix_crop(ll_lh_hl_hh_add_crop, filt_len-2, 2*h)
    y = tf.roll(y, 1-filt_len//2, axis=1)

    return y


def analysis_filter_bank2d_ghm(x, lp1, lp2, hp1, hp2):
    # parameters
    conv_type = 'same'
    h = int(x.shape[1])
    w = int(x.shape[2])

    filt_len = int(lp1.shape[1])
    x_os = over_sample_rows(x)
    x_pad = tf.pad(x_os,[[0, 0], [filt_len, filt_len], [0, 0], [0, 0]], mode='CONSTANT',constant_values=0)

    lp1_ds = fir_down_sample(x_pad, lp1, filt_len-2)
    lp1_ds1 = lp1_ds[:, 0:lp1_ds.shape[1]-5:2, :, :]

    lp2_ds = fir_down_sample(x_pad, lp2, filt_len-2)
    lp2_ds1 = lp2_ds[:, 2:lp2_ds.shape[1]-3:2, :, :]

    hp1_ds = fir_down_sample(x_pad, hp1, filt_len-2)
    hp1_ds1 = hp1_ds[:, 0:lp1_ds.shape[1]-5:2, :, :]

    hp2_ds = fir_down_sample(x_pad, hp2, filt_len-2)
    hp2_ds1 = hp2_ds[:, 2:lp2_ds.shape[1]-3:2, :, :]*(-1)

    lp1_ds1_tr = tf.transpose(lp1_ds1, perm=[0,2,1,3])
    lp2_ds1_tr = tf.transpose(lp2_ds1, perm=[0,2,1,3])
    hp1_ds1_tr = tf.transpose(hp1_ds1, perm=[0,2,1,3])
    hp2_ds1_tr = tf.transpose(hp2_ds1, perm=[0,2,1,3])

    lp1_ds1_os = over_sample_rows(lp1_ds1_tr)
    lp2_ds1_os = over_sample_rows(lp2_ds1_tr)
    hp1_ds1_os = over_sample_rows(hp1_ds1_tr)
    hp2_ds1_os = over_sample_rows(hp2_ds1_tr)

    lp1_ds1_os_pad = tf.pad(lp1_ds1_os,[[0, 0], [filt_len, filt_len], [0, 0], [0, 0]], mode='CONSTANT',constant_values=0)
    lp2_ds1_os_pad = tf.pad(lp2_ds1_os,[[0, 0], [filt_len, filt_len], [0, 0], [0, 0]], mode='CONSTANT',constant_values=0)
    hp1_ds1_os_pad = tf.pad(hp1_ds1_os,[[0, 0], [filt_len, filt_len], [0, 0], [0, 0]], mode='CONSTANT',constant_values=0)
    hp2_ds1_os_pad = tf.pad(hp2_ds1_os,[[0, 0], [filt_len, filt_len], [0, 0], [0, 0]], mode='CONSTANT',constant_values=0)

    lp1_lp1_ds = fir_down_sample(lp1_ds1_os_pad, lp1, start=filt_len-2, step=4)
    lp1_hp1_ds = fir_down_sample(lp1_ds1_os_pad, hp1, start=filt_len-2, step=4)
    hp1_lp1_ds = fir_down_sample(hp1_ds1_os_pad, lp1, start=filt_len-2, step=4)
    hp1_hp1_ds = fir_down_sample(hp1_ds1_os_pad, hp1, start=filt_len-2, step=4)

    lp1_lp1_tr = tf.transpose(lp1_lp1_ds[:,:-3,:,:], perm=[0,2,1,3])
    lp1_hp1_tr = tf.transpose(lp1_hp1_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp1_lp1_tr = tf.transpose(hp1_lp1_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp1_hp1_tr = tf.transpose(hp1_hp1_ds[:,:-3,:,:], perm=[0,2,1,3])

    lp1_lp2_ds = fir_down_sample(lp1_ds1_os_pad, lp2, start=filt_len-2, step=4)
    lp1_hp2_ds = fir_down_sample(lp1_ds1_os_pad, hp2, start=filt_len-2, step=4)
    hp1_lp2_ds = fir_down_sample(hp1_ds1_os_pad, lp2, start=filt_len-2, step=4)
    hp1_hp2_ds = fir_down_sample(hp1_ds1_os_pad, hp2, start=filt_len-2, step=4)

    lp1_lp2_tr = tf.transpose(lp1_lp2_ds[:,:-3,:,:], perm=[0,2,1,3])
    lp1_hp2_tr = tf.transpose(lp1_hp2_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp1_lp2_tr = tf.transpose(hp1_lp2_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp1_hp2_tr = tf.transpose(hp1_hp2_ds[:,:-3,:,:], perm=[0,2,1,3])

    lp2_lp1_ds = fir_down_sample(lp2_ds1_os_pad, lp1, start=filt_len-2, step=4)
    lp2_hp1_ds = fir_down_sample(lp2_ds1_os_pad, hp1, start=filt_len-2, step=4)
    hp2_lp1_ds = fir_down_sample(hp2_ds1_os_pad, lp1, start=filt_len-2, step=4)
    hp2_hp1_ds = fir_down_sample(hp2_ds1_os_pad, hp1, start=filt_len-2, step=4)

    lp2_lp1_tr = tf.transpose(lp2_lp1_ds[:,:-3,:,:], perm=[0,2,1,3])
    lp2_hp1_tr = tf.transpose(lp2_hp1_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp2_lp1_tr = tf.transpose(hp2_lp1_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp2_hp1_tr = tf.transpose(hp2_hp1_ds[:,:-3,:,:], perm=[0,2,1,3])

    lp2_lp2_ds = fir_down_sample(lp2_ds1_os_pad, lp2, start=filt_len-2, step=4)
    lp2_hp2_ds = fir_down_sample(lp2_ds1_os_pad, hp2, start=filt_len-2, step=4)
    hp2_lp2_ds = fir_down_sample(hp2_ds1_os_pad, lp2, start=filt_len-2, step=4)
    hp2_hp2_ds = fir_down_sample(hp2_ds1_os_pad, hp2, start=filt_len-2, step=4)

    lp2_lp2_tr = tf.transpose(lp2_lp2_ds[:,:-3,:,:], perm=[0,2,1,3])
    lp2_hp2_tr = tf.transpose(lp2_hp2_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp2_lp2_tr = tf.transpose(hp2_lp2_ds[:,:-3,:,:], perm=[0,2,1,3])
    hp2_hp2_tr = tf.transpose(hp2_hp2_ds[:,:-3,:,:], perm=[0,2,1,3])

    res = [[lp1_lp1_tr, lp1_hp1_tr,hp1_lp1_tr, hp1_hp1_tr],
           [lp1_lp2_tr, lp1_hp2_tr,hp1_lp2_tr, hp1_hp2_tr],
           [lp2_lp1_tr, lp2_hp1_tr,hp2_lp1_tr, hp2_hp1_tr],
           [lp2_lp2_tr, lp2_hp2_tr,hp2_lp2_tr, hp2_hp2_tr],
           ]
    return res
