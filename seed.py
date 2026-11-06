"""Illustrative SAMPLE data (synthetic photos, invented complaints) for demos and tests.
Locations are approximate Chennai points used only for visualisation; this is NOT real
municipal data and says nothing about the real condition of these streets."""
import os

import core
import db
import synth
from util import iso, now

W = [(1, "Sample Ward A (Central)", 13.0604, 80.2496), (2, "Sample Ward B (South)", 12.9815, 80.2180),
     (3, "Sample Ward C (West)", 13.0418, 80.2341), (4, "Sample Ward D (Coastal)", 13.0063, 80.2574),
     (5, "Sample Ward E (North)", 13.1167, 80.2332), (6, "Sample Ward F (Industrial)", 13.0067, 80.2206)]

PLACES = [("Sample Govt School", "school", 13.0607, 80.2499), ("Sample Hospital", "hospital", 12.9811, 80.2174),
          ("Sample School", "school", 13.1169, 80.2336)]

U = os.path.join(core.UPLOADS)


def _img(kind, name, seed=1, **kw):
    path = os.path.join(U, name)
    if not os.path.exists(path):
        getattr(synth, kind)(path, seed=seed, **kw)
    return path


def seed_sample(conn):
    for w in W:
        conn.execute("INSERT OR IGNORE INTO wards VALUES (?,?,?,?)", w)
    for p in PLACES:
        conn.execute("INSERT INTO sensitive_places(name,kind,lat,lon) VALUES (?,?,?,?)", p)
    conn.commit()

    def day(n):
        return iso(now(n))

    # A: recurring pothole near a school (3 episodes) - the headline example
    lat, lon = 13.0604, 80.2496
    r = core.submit_complaint(conn, description="Large pothole near the school bus stop, two-wheelers skid here",
                              lat=lat, lon=lon, image_path=_img("pothole", "s_a1.jpg", 11), created_at=day(-200),
                              is_sample=True, location_text="Sample Street, Ward A")
    core.complete_repair(conn, r["asset_id"], officer="Sample Officer 1", notes="cold-mix patch",
                         after_image=_img("pothole", "s_a1r.jpg", 11, repaired=True), completed_at=day(-190))
    core.submit_complaint(conn, description="pothole again at the same place", lat=lat + 0.00005, lon=lon,
                          image_path=_img("pothole", "s_a2.jpg", 12), created_at=day(-120), is_sample=True)
    core.complete_repair(conn, r["asset_id"], officer="Sample Officer 2", notes="re-patched",
                         after_image=_img("pothole", "s_a2r.jpg", 12, repaired=True), completed_at=day(-112))
    core.submit_complaint(conn, description="பள்ளி அருகில் மீண்டும் சாலையில் பெரிய பள்ளம், ஆபத்து",
                          lat=lat, lon=lon + 0.00004, image_path=_img("pothole", "s_a3.jpg", 13),
                          created_at=day(-50), is_sample=True)
    core.submit_complaint(conn, description="Pothole is dangerous at night, someone fell from a bike",
                          lat=lat + 0.00003, lon=lon, image_path=_img("pothole", "s_a4.jpg", 14, shift=12),
                          created_at=day(-48), is_sample=True)

    # B: drain + waterlogging near a hospital
    lat, lon = 12.9815, 80.2180
    core.submit_complaint(conn, description="Drain is blocked and sewage overflowing onto the road", lat=lat, lon=lon,
                          created_at=day(-14), is_sample=True)
    core.submit_complaint(conn, description="தண்ணீர் தேங்கி நிற்கிறது, மருத்துவமனை அருகில்", lat=lat + 0.0002,
                          lon=lon + 0.0002, created_at=day(-6), is_sample=True)

    # C: garbage
    core.submit_complaint(conn, description="Garbage dumped near the market for a week", lat=13.0418, lon=80.2341,
                          image_path=_img("garbage", "s_c1.jpg", 21), created_at=day(-9), is_sample=True)

    # D: crack
    core.submit_complaint(conn, description="Long crack running across the road", lat=13.0063, lon=80.2574,
                          image_path=_img("crack", "s_d1.jpg", 31), created_at=day(-20), is_sample=True)

    # E: school-adjacent pothole, repaired once (1 episode, no recurrence yet)
    lat, lon = 13.1167, 80.2332
    r = core.submit_complaint(conn, description="pothole beside school gate", lat=lat, lon=lon,
                              image_path=_img("pothole", "s_e1.jpg", 41), created_at=day(-40), is_sample=True)
    core.complete_repair(conn, r["asset_id"], officer="Sample Officer 1", notes="patched",
                         after_image=_img("pothole", "s_e1r.jpg", 41, repaired=True), completed_at=day(-33))

    # F: a pothole cluster (hotspot) - four separate road sections ~50 m apart
    for i, (dy, dx) in enumerate([(0, 0), (0.00045, 0.0001), (0.0009, 0.0002), (0.0013, 0.0002)]):
        core.submit_complaint(conn, description=f"Pothole on the main road section {i + 1}",
                              lat=13.0067 + dy, lon=80.2206 + dx,
                              image_path=_img("pothole", f"s_f{i}.jpg", 50 + i), created_at=day(-12 + i),
                              is_sample=True)
    conn.commit()


def full_reset(sample=True):
    db.reset_db()
    conn = db.connect()
    if sample:
        seed_sample(conn)
    else:
        for w in W:
            conn.execute("INSERT OR IGNORE INTO wards VALUES (?,?,?,?)", w)
        for p in PLACES:
            conn.execute("INSERT INTO sensitive_places(name,kind,lat,lon) VALUES (?,?,?,?)", p)
        conn.commit()
    conn.close()


if __name__ == "__main__":
    full_reset(True)
    print("sample data loaded")
