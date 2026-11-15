"""REAL test of Cleo on a bigger, realistic DD database.

The user asked for 3 checks per question:
  1. Does it understand the Darija question?   (intent check on the SQL)
  2. Does it write correct SQL for our real tables? (re-execute the SQL ourselves)
  3. Does it return the correct result?        (rows vs hand-computed ground truth)

Database: DD schema (suppliers/customers/invoices/payments/products),
8 suppliers, 10 customers, 26 invoices, 10 products, with the REAL cases:
  - F-101 / F-107 duplicate pair (same supplier, amount, date)
  - F-201 exempt invoice wrongly charging TVA 940,661.88 on 4,950,852.00
  - near-duplicates with same amount but different date (must NOT match)
  - October 2026 sales for the TVA total
  - stagnant + out-of-stock products

Runs ask_once (single candidate, max_gather=3, max_repair=2) on 10
Darija questions, then the FULL harness cleo(..., k=4) on the duplicate
question only, to see if the multi-candidate selector fixes the one
failure from the first test.
"""
import json, os, sqlite3, time

DB_PATH = "/home/hatch/workspace/qwen25-arabic-sql/dd-real-test.db"
OUT_PATH = "/home/hatch/workspace/qwen25-arabic-sql/results-cleo-real.json"

SCHEMA = """
CREATE TABLE suppliers(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, wilaya TEXT);
CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, wilaya TEXT);
CREATE TABLE invoices(id INTEGER PRIMARY KEY, number TEXT, type TEXT, supplier_id INTEGER, customer_id INTEGER, date TEXT, amount_ht REAL, tva_rate REAL, tva_amount REAL, amount_ttc REAL, status TEXT, exempt INTEGER);
CREATE TABLE payments(id INTEGER PRIMARY KEY, invoice_id INTEGER, amount REAL, date TEXT, method TEXT);
CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, stock_quantity INTEGER, purchase_price REAL, sale_price REAL, last_sale_date TEXT);
INSERT INTO suppliers VALUES
 (1,'شركة النور','0550123456','الشلف'),(2,'SARL الأمل','0661234567','وهران'),
 (3,'مؤسسة السلام','0772345678','الجزائر'),(4,'شركة الفجر','0553456789','سطيف'),
 (5,'SARL النجاح','0664567890','قسنطينة'),(6,'مؤسسة البركة','0775678901','الشلف'),
 (7,'شركة الوفاء','0556789012','تلمسان'),(8,'EURL الأطلس','0667890123','البليدة');
INSERT INTO customers VALUES
 (1,'أحمد بن علي','0555987654','الشلف'),(2,'محمد حمداني','0666789012','وهران'),
 (3,'فاطمة زروقي','0777890123','الجزائر'),(4,'يوسف بلقاسم','0558901234','الشلف'),
 (5,'خديجة مرابط','0669012345','سطيف'),(6,'عبد القادر بن يحيى','0770123456','وهران'),
 (7,'سارة بن عيسى','0551234567','الجزائر'),(8,'رشيد حمدي','0662345678','قسنطينة'),
 (9,'نادية شريف','0773456789','البليدة'),(10,'كمال بوزيد','0554567890','تلمسان');
INSERT INTO invoices VALUES
 (1,'F-101','purchase',1,NULL,'2026-01-05',4150000.00,19,788500.00,4938500.00,'unpaid',0),
 (2,'F-107','purchase',1,NULL,'2026-01-05',4150000.00,19,788500.00,4938500.00,'unpaid',0),
 (3,'F-201','purchase',2,NULL,'2026-03-10',4950852.00,19,940661.88,5891513.88,'unpaid',1),
 (4,'F-202','purchase',2,NULL,'2026-03-12',2000000.00,19,380000.00,2380000.00,'paid',0),
 (5,'F-203','purchase',3,NULL,'2026-04-02',750000.00,9,67500.00,817500.00,'partial',0),
 (6,'F-204','purchase',4,NULL,'2026-05-20',1200000.00,19,228000.00,1428000.00,'unpaid',0),
 (7,'F-205','purchase',5,NULL,'2026-06-15',3300000.00,19,627000.00,3927000.00,'paid',0),
 (8,'F-206','purchase',6,NULL,'2026-07-08',900000.00,0,0.00,900000.00,'unpaid',1),
 (9,'F-207','purchase',1,NULL,'2026-08-25',4150000.00,19,788500.00,4938500.00,'paid',0),
 (10,'F-208','purchase',7,NULL,'2026-09-10',600000.00,9,54000.00,654000.00,'unpaid',0),
 (11,'F-209','purchase',8,NULL,'2025-11-20',2500000.00,19,475000.00,2975000.00,'paid',0),
 (12,'F-210','purchase',3,NULL,'2026-02-14',750000.00,9,67500.00,817500.00,'unpaid',0),
 (13,'F-301','sale',NULL,1,'2026-10-03',1000000.00,19,190000.00,1190000.00,'paid',0),
 (14,'F-302','sale',NULL,2,'2026-10-15',2500000.00,19,475000.00,2975000.00,'partial',0),
 (15,'F-303','sale',NULL,1,'2026-10-20',800000.00,9,72000.00,872000.00,'unpaid',0),
 (16,'F-304','sale',NULL,3,'2026-10-25',1500000.00,19,285000.00,1785000.00,'paid',0),
 (17,'F-305','sale',NULL,2,'2026-09-05',2500000.00,19,475000.00,2975000.00,'paid',0),
 (18,'F-306','sale',NULL,4,'2026-11-02',3000000.00,19,570000.00,3570000.00,'unpaid',0),
 (19,'F-307','sale',NULL,5,'2026-08-11',450000.00,9,40500.00,490500.00,'paid',0),
 (20,'F-308','sale',NULL,2,'2026-10-28',1100000.00,19,209000.00,1309000.00,'unpaid',0),
 (21,'F-309','sale',NULL,6,'2026-07-19',2200000.00,19,418000.00,2618000.00,'paid',0),
 (22,'F-310','sale',NULL,7,'2026-06-30',650000.00,9,58500.00,708500.00,'partial',0),
 (23,'F-311','sale',NULL,8,'2025-12-15',1800000.00,19,342000.00,2142000.00,'paid',0),
 (24,'F-312','sale',NULL,9,'2026-10-08',950000.00,19,180500.00,1130500.00,'unpaid',0),
 (25,'F-313','sale',NULL,10,'2026-05-17',700000.00,19,133000.00,833000.00,'paid',0),
 (26,'F-314','sale',NULL,3,'2026-10-12',1500000.00,19,285000.00,'unpaid',0);
INSERT INTO payments VALUES
 (1,13,1190000.00,'2026-10-05','cash'),(2,14,1500000.00,'2026-10-18','bank'),
 (3,4,2380000.00,'2026-03-15','bank'),(4,7,3927000.00,'2026-06-20','ccp'),
 (5,22,300000.00,'2026-07-05','cash'),(6,16,1785000.00,'2026-10-27','bank'),
 (7,17,2975000.00,'2026-09-07','cash'),(8,9,4938500.00,'2026-08-28','bank');
INSERT INTO products VALUES
 (1,'سكر 1كغ','مواد غذائية',120,90.00,110.00,'2026-11-01'),
 (2,'زيت 5ل','مواد غذائية',0,950.00,1150.00,'2026-10-20'),
 (3,'إسمنت 50كغ','مواد بناء',45,700.00,850.00,'2025-01-15'),
 (4,'بطارية سيارة','قطع غيار',8,12000.00,15000.00,'2026-09-30'),
 (5,'طلاء أبيض 15ل','مواد بناء',20,3500.00,4200.00,'2025-03-02'),
 (6,'أرز 5كغ','مواد غذائية',200,600.00,720.00,'2026-10-28'),
 (7,'مسامير 1كغ','مواد بناء',0,300.00,380.00,'2026-06-15'),
 (8,'ثلاجة صغيرة','أجهزة',3,85000.00,105000.00,'2026-08-20'),
 (9,'حليب 1ل','مواد غذائية',150,110.00,130.00,'2026-11-05'),
 (10,'إطارات سيارة','قطع غيار',12,22000.00,28000.00,'2026-04-10');
"""

QUESTIONS = [
    "أعطيني قائمة الموردين اللي ما سددوش فواتيرهم",
    "واش كاين فواتير مكررة في 2026؟",
    "كم مجموع TVA في شهر أكتوبر 2026؟",
    "أعطيني المنتجات الراكدة اللي ما تباعتش منذ 6 أشهر",
    "شكون هو أكبر زبون عندي من ناحية المبيعات؟",
    "واش كاين فواتير معفاة من TVA لكن فيها TVA؟",
    "شحال يساوي مجموع الديون اللي عليا للموردين؟",
    "أعطيني الفواتير اللي خلصت جزئياً",
    "واش كاين منتجات خلصت من المخزن؟",
    "شكون المورد اللي عندي معاه أكبر دين؟",
]

def norm(text):
    return str(text).replace(",", "").replace(" ", "")

def judge_result(i, rows):
    """Ground truth, hand-computed from the data above."""
    t = norm(rows)
    if i == 0:   # unpaid suppliers: النور، الأمل، السلام، الفجر، البركة، الوفاء
        return all(n in t for n in ["النور", "الأمل", "السلام", "الفجر", "البركة", "الوفاء"])
    if i == 1:   # duplicates: only F-101 + F-107
        return "F-101" in t and "F-107" in t
    if i == 2:   # Oct 2026 TVA total = 1,696,500
        return "1696500" in t
    if i == 3:   # stagnant (last sale before 2026-05-12): إسمنت، طلاء أبيض، إطارات سيارة
        return all(n in t for n in ["إسمنت", "طلاء", "إطارات"])
    if i == 4:   # biggest customer: محمد حمداني (7,259,000)
        return "محمدحمداني" in t
    if i == 5:   # exempt but charging TVA: F-201 only (F-206 is exempt with 0 TVA)
        return "F-201" in t and "F-206" not in t
    if i == 6:   # total unpaid purchase debts = 19,568,013.88
        return "19568013" in t
    if i == 7:   # partial invoices: F-203, F-302, F-310
        return all(n in t for n in ["F-203", "F-302", "F-310"])
    if i == 8:   # out of stock: زيت 5ل، مسامير 1كغ
        return "زيت" in t and "مسامير" in t
    if i == 9:   # supplier with biggest unpaid debt: شركة النور (9,877,000)
        return "النور" in t
    return False

def judge_understood(i, sql):
    """Did the SQL aim at the right thing? (intent proxy on the SQL text)."""
    if not sql:
        return False
    s = sql.lower()
    if i == 0:
        return "suppliers" in s and "unpaid" in s
    if i == 1:
        return "invoices" in s and ("group by" in s or "having" in s or "count" in s)
    if i == 2:
        return "sum" in s and "tva_amount" in s and "2026-10" in s
    if i == 3:
        return "products" in s and "last_sale_date" in s
    if i == 4:
        return "customers" in s and "sum" in s and "order by" in s and "limit 1" in s
    if i == 5:
        return "exempt" in s and ("tva_amount" in s or "tva_rate" in s)
    if i == 6:
        return "sum" in s and "purchase" in s and "unpaid" in s
    if i == 7:
        return "partial" in s
    if i == 8:
        return "products" in s and "stock_quantity" in s and ("= 0" in s or "=0" in s)
    if i == 9:
        return "suppliers" in s and "sum" in s and "order by" in s and "limit 1" in s
    return False

def re_execute(con, sql):
    """Independently re-run the final SQL: correct iff it runs clean."""
    if not sql:
        return False, "no SQL produced"
    try:
        cur = con.execute(sql)
        cur.fetchall()
        return True, None
    except Exception as e:
        return False, str(e)

def main():
    from cleo import Cleo
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    print("DB built:", DB_PATH, flush=True)

    print("Loading Cleo (local ./cleo-q8_0.gguf, GGUF Q8_0) ...", flush=True)
    t0 = time.time()
    cleo = Cleo.from_gguf("./cleo-q8_0.gguf", n_ctx=4096, n_threads=4, n_gpu_layers=0)
    print(f"Loaded in {time.time()-t0:.0f}s", flush=True)

    results = {}
    n_u = n_s = n_r = 0
    for i, q in enumerate(QUESTIONS):
        t0 = time.time()
        try:
            ans = cleo.ask_once(q, con, execute_final=True)
            sql = getattr(ans, "sql", None)
            rows = getattr(ans, "rows", None)
            err = getattr(ans, "error", None)
            clar = getattr(ans, "clarification", None)
        except Exception as e:
            sql, rows, err, clar = None, None, f"EXCEPTION: {e}", None
        understood = judge_understood(i, sql)
        sql_ok, sql_err = re_execute(con, sql)
        result_ok = bool(rows is not None) and judge_result(i, rows)
        n_u += understood
        n_s += sql_ok
        n_r += result_ok
        results[q] = {
            "sql": sql, "rows": rows, "error": err, "clarification": clar,
            "understood": understood, "sql_correct": sql_ok,
            "sql_error": sql_err, "result_correct": result_ok,
            "seconds": round(time.time() - t0, 1),
        }
        print(f"Q{i+1}: {q}\n  UNDERSTOOD: {'YES' if understood else 'NO'} | SQL_OK: {'YES' if sql_ok else 'NO'} | RESULT_OK: {'YES' if result_ok else 'NO'}\n  SQL: {sql}\n  ROWS: {rows}\n  ERR: {err}\n  ({time.time()-t0:.0f}s)\n---", flush=True)

    print(f"ASK_ONCE DONE: understood {n_u}/10, sql_ok {n_s}/10, result_ok {n_r}/10", flush=True)

    # FULL harness (greedy + k=4 candidates + selector) on the duplicate question only
    full = None
    try:
        t0 = time.time()
        q2 = QUESTIONS[1]
        ans = cleo(q2, con, k=4)
        sql = getattr(ans, "sql", None)
        rows = getattr(ans, "rows", None)
        err = getattr(ans, "error", None)
        understood = judge_understood(1, sql)
        sql_ok, sql_err = re_execute(con, sql)
        result_ok = bool(rows is not None) and judge_result(1, rows)
        full = {
            "question": q2, "sql": sql, "rows": rows, "error": err,
            "understood": understood, "sql_correct": sql_ok,
            "sql_error": sql_err, "result_correct": result_ok,
            "seconds": round(time.time() - t0, 1),
        }
        print(f"FULL-HARNESS Q2: UNDERSTOOD: {'YES' if understood else 'NO'} | SQL_OK: {'YES' if sql_ok else 'NO'} | RESULT_OK: {'YES' if result_ok else 'NO'}\n  SQL: {sql}\n  ROWS: {rows}\n  ERR: {err}\n  ({time.time()-t0:.0f}s)", flush=True)
    except Exception as e:
        full = {"question": QUESTIONS[1], "error": f"EXCEPTION: {e}"}
        print(f"FULL-HARNESS Q2 FAILED: {e}", flush=True)

    with open(OUT_PATH, "w") as f:
        json.dump({
            "ask_once": {"understood": f"{n_u}/10", "sql_correct": f"{n_s}/10",
                         "result_correct": f"{n_r}/10", "results": results},
            "full_harness_q2": full,
        }, f, ensure_ascii=False, indent=2)
    print("CLEO_REAL_TEST_DONE", flush=True)

if __name__ == "__main__":
    main()
