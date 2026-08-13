import sys
import klayout.db as db

GDS = sys.argv[1] if len(sys.argv) > 1 else \
    "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
TOP_CELL = "i2c_slave_async_nrow_fm"

layout = db.Layout()
layout.read(GDS)
dbu = layout.dbu
top = layout.cell(TOP_CELL)


def idx(l):
    return layout.layer(*l)


def check(layer, minw, mins, label):
    r = db.Region(top.begin_shapes_rec(idx(layer))).merged()
    w = r.width_check(int(round(minw / dbu)))
    s = r.space_check(int(round(mins / dbu)))
    print(f"{label}: width viol={w.count()} space viol={s.count()}")


check((13, 0), 1.8, 1.4, 'M1')
check((20, 0), 3.0, 2.0, 'M2')

m1 = db.Region(top.begin_shapes_rec(idx((13, 0)))).merged()
m2 = db.Region(top.begin_shapes_rec(idx((20, 0)))).merged()
gc = db.Region(top.begin_shapes_rec(idx((8, 1)))).merged()
v1 = db.Region(top.begin_shapes_rec(idx((19, 0))))

print('V1 space viol:', v1.space_check(int(round(1.5 / dbu))).count())
print('V1 enclosed by M1<1.0 viol:', v1.enclosed_check(m1, int(round(1.0 / dbu))).count())
print('V1 enclosed by M2<1.0 viol:', v1.enclosed_check(m2, int(round(1.0 / dbu))).count())
print('V1-GC space<1.2 viol:', v1.separation_check(gc, int(round(1.2 / dbu))).count())
