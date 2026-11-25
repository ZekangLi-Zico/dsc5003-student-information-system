"""Synthetic student personas: names, IDs, contacts.

No real personal data is used. Everything is generated from a fixed seed so
the database is byte-for-byte reproducible.

Conventions follow HKU practice:
  * English name  : SURNAME in capitals + given name, e.g. "CHAN Tai Man"
  * Chinese name  : surname char + one or two given chars, e.g. "陳大文"
  * student_id    : 10 characters, "3036" + 6-digit sequence
  * phone_hk      : 8 digits, first digit in 5..9 (HK mobile range)
  * email         : <surname>.<given>@connect.hku.hk, deduplicated
"""
import random

SURNAMES = [
    ("CHAN",   "陳"), ("WONG",   "黃"), ("LEE",    "李"), ("CHEUNG", "張"),
    ("LEUNG",  "梁"), ("LAU",    "劉"), ("NG",     "吳"), ("HO",     "何"),
    ("TAM",    "譚"), ("LAM",    "林"), ("FUNG",   "馮"), ("TSE",    "謝"),
    ("MAK",    "麥"), ("YIP",    "葉"), ("TSANG",  "曾"), ("CHOW",   "周"),
    ("SUEN",   "孫"), ("KWOK",   "郭"), ("MA",     "馬"), ("TANG",   "鄧"),
    ("YEUNG",  "楊"), ("HUI",    "許"), ("KO",     "高"), ("LO",     "盧"),
    ("CHOI",   "蔡"), ("PANG",   "彭"), ("YUEN",   "袁"), ("SIU",    "蕭"),
    ("TONG",   "唐"), ("YAU",    "邱"), ("SZE",    "施"), ("LI",     "黎"),
    ("LUI",    "呂"), ("AU",     "歐"), ("PUN",    "潘"), ("HUNG",   "洪"),
    ("MOK",    "莫"), ("KAN",    "簡"), ("TSUI",   "徐"), ("LAI",    "賴"),
]

GIVEN_EN = [
    "Tai Man", "Siu Ming", "Ka Ho", "Wing Yan", "Man Wai", "Chi Kin",
    "Ho Yin", "Yat Long", "Cheuk Ting", "Pui Sze", "Hiu Tung", "Tsz Ching",
    "Yuen Ting", "Lok Man", "Hei Ching", "Yan Nok", "Chun Kit", "Ming Him",
    "Wai Hong", "Kei Man", "Ting Yee", "Mei Suet", "Sze Man", "Lai Yee",
    "Pui Yan", "Kwun Ho", "Shun Yat", "Yin Tik", "Cheung Him", "Yau Ka",
    "Ka Lok", "Wing Hei", "Man Ching", "Ho Ching", "Tsz Ho", "Yat Hang",
    "Ching Yan", "Nok Chi", "Siu Yan", "Tung Man", "Him Nok", "Yee Tung",
    "Pak Ho", "Siu Hei", "Ting Nok", "Man Ho", "Ka Yan", "Wai Ching",
    "Yin Man", "Ho Man",
]

GIVEN_ZH = [
    "大文", "小明", "家豪", "詠欣", "文慧", "志堅", "昊然", "日朗", "卓婷",
    "佩詩", "曉彤", "子晴", "婉婷", "樂文", "晞晴", "恩諾", "俊傑", "明謙",
    "偉康", "琪文", "婷怡", "美雪", "思敏", "麗怡", "佩欣", "君豪", "舜匡",
    "彥恩", "晉謙", "彤昕", "嘉朗", "瑋晴", "文清", "皓晴", "子豪", "日恒",
    "靖欣", "諾芝", "小欣", "冬文", "謙諾", "怡冬", "柏豪", "小晞", "婷諾",
    "文豪", "嘉欣", "慧晴", "茵文", "皓文",
]


def make_student_id(seq):
    """10-character HKU-style university number."""
    return "3036%06d" % seq


def make_phone(rng):
    """8-digit HK mobile number, first digit 5-9."""
    return "%d%s" % (rng.randint(5, 9), "".join(rng.choice("0123456789") for _ in range(7)))


def make_email(surname_en, given_en, student_id, taken):
    """Unique connect.hku.hk address; falls back to the uid on collision."""
    first = given_en.split()[0].lower()
    base = "%s.%s" % (surname_en.lower(), first)
    email = "%s@connect.hku.hk" % base
    if email not in taken:
        taken.add(email)
        return email
    # collision: append digits of the uid, then keep incrementing
    for k in range(2, 400):
        cand = "%s%d@connect.hku.hk" % (base, k)
        if cand not in taken:
            taken.add(cand)
            return cand
    # last resort: uid-based address (always unique)
    cand = "%s@connect.hku.hk" % student_id.lower()
    taken.add(cand)
    return cand


def make_person(rng, seq, gender):
    """Return a dict with name/identity/contact fields for one student."""
    sur_en, sur_zh = rng.choice(SURNAMES)
    gi = rng.randrange(len(GIVEN_EN))
    given_en = GIVEN_EN[gi]
    given_zh = GIVEN_ZH[gi % len(GIVEN_ZH)]
    sid = make_student_id(seq)
    return {
        "student_id": sid,
        "name_en": "%s %s" % (sur_en, given_en),
        "name_zh": "%s%s" % (sur_zh, given_zh),
        "gender": gender,
        "phone_hk": make_phone(rng),
        "_email": make_email(sur_en, given_en, sid, set()),  # replaced below
    }


def make_people(rng, n):
    """Generate n distinct personas with globally unique emails."""
    taken = set()
    out = []
    for i in range(1, n + 1):
        sur_en, sur_zh = rng.choice(SURNAMES)
        gi = rng.randrange(len(GIVEN_EN))
        given_en = GIVEN_EN[gi]
        given_zh = GIVEN_ZH[gi % len(GIVEN_ZH)]
        sid = make_student_id(i)
        gender = rng.choices(["F", "M"], weights=[0.52, 0.48])[0]
        out.append({
            "student_id": sid,
            "name_en": "%s %s" % (sur_en, given_en),
            "name_zh": "%s%s" % (sur_zh, given_zh),
            "gender": gender,
            "phone_hk": make_phone(rng),
            "email": make_email(sur_en, given_en, sid, taken),
        })
    return out


if __name__ == "__main__":
    r = random.Random(1)
    people = make_people(r, 12)
    for p in people:
        print(p)
    emails = [p["email"] for p in make_people(random.Random(1), 1000)]
    print("\n1000 emails unique:", len(set(emails)) == 1000)
    import re
    bad = [e for e in emails if not re.match(r"^[a-z0-9.]+@connect\.hku\.hk$", e)]
    print("emails failing the CHECK pattern:", len(bad))
    ids = [p["student_id"] for p in make_people(random.Random(1), 1000)]
    print("ids unique & len 10:", len(set(ids)) == 1000, all(len(i) == 10 for i in ids))
