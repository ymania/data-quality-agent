"""Generate reproducible Faker orders for demo_orders_faker.

Preview is the default. Pass --write to insert the generated rows into MySQL.
Run from the project root: python -m scripts.generate_orders --rows 10000
"""

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

ALLOWED_STATUSES = ("NEW", "PAID", "CANCELLED")
BAD_STATUSES = ("UNKNOWN", "REFUNDED", "new", "PAID ")
CUSTOMER_ERRORS = (None, "", "   ")
DATE_START = datetime(2025, 1, 1)
DATE_END = datetime(2025, 12, 31, 23, 59, 59)
INSERT_SQL = (
    "INSERT INTO demo_orders_faker "
    "(order_id, customer_name, order_status, amount, created_at) "
    "VALUES (%s,%s,%s,%s,%s)"
)


@dataclass(frozen=True)
class Options:
    rows: int
    seed: int
    start_id: int
    batch_size: int
    customer_error_rate: float
    status_error_rate: float
    status_null_rate: float


@dataclass
class Summary:
    total: int = 0
    bad_customer: int = 0
    bad_status: int = 0
    null_status: int = 0
    first_rows: list = field(default_factory=list)
    first_anomalies: list = field(default_factory=list)

    def add(self, row):
        order_id, customer, status, amount, created_at = row
        self.total += 1
        customer_bad = customer is None or customer.strip() == ""
        status_bad = status is not None and status not in ALLOWED_STATUSES
        self.bad_customer += int(customer_bad)
        self.bad_status += int(status_bad)
        self.null_status += int(status is None)
        preview = {
            "order_id": order_id,
            "customer_name": customer,
            "order_status": status,
            "amount": str(amount),
            "created_at": created_at.isoformat(sep=" ", timespec="seconds"),
        }
        if len(self.first_rows) < 5:
            self.first_rows.append(preview)
        if (customer_bad or status_bad) and len(self.first_anomalies) < 5:
            self.first_anomalies.append(preview)

    def as_dict(self, options):
        checked_status = self.total - self.null_status
        rate = lambda passed, checked: (
            str((Decimal(passed) * 100 / Decimal(checked)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if checked else None
        )
        return {
            "table": "demo_orders_faker",
            "seed": options.seed,
            "start_id": options.start_id,
            "end_id": options.start_id + self.total - 1,
            "rows": self.total,
            "customer_not_null": {
                "checked": self.total,
                "passed": self.total - self.bad_customer,
                "failed": self.bad_customer,
                "skipped": 0,
                "pass_rate": rate(self.total - self.bad_customer, self.total),
            },
            "status_enum": {
                "checked": checked_status,
                "passed": checked_status - self.bad_status,
                "failed": self.bad_status,
                "skipped": self.null_status,
                "pass_rate": rate(checked_status - self.bad_status, checked_status),
            },
            "first_rows": self.first_rows,
            "first_anomalies": self.first_anomalies,
        }


def generate_rows(options):
    """Yield rows without holding the whole data set in memory."""
    from faker import Faker

    fake = Faker("zh_CN")
    fake.seed_instance(options.seed)
    rng = random.Random(options.seed)
    for offset in range(options.rows):
        customer = fake.name()
        if rng.random() < options.customer_error_rate:
            customer = rng.choice(CUSTOMER_ERRORS)

        status_roll = rng.random()
        if status_roll < options.status_null_rate:
            status = None
        elif status_roll < options.status_null_rate + options.status_error_rate:
            status = rng.choice(BAD_STATUSES)
        else:
            status = rng.choice(ALLOWED_STATUSES)

        amount = Decimal(rng.randint(100, 500000)) / Decimal(100)
        created_at = fake.date_time_between_dates(datetime_start=DATE_START, datetime_end=DATE_END).replace(microsecond=0)
        yield (options.start_id + offset, customer, status, amount, created_at)


def preview(options):
    summary = Summary()
    for row in generate_rows(options):
        summary.add(row)
    return summary


def write(options):
    from app.db import connect

    summary = Summary()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM demo_orders_faker WHERE order_id BETWEEN %s AND %s",
                (options.start_id, options.start_id + options.rows - 1),
            )
            if cur.fetchone()["n"]:
                raise RuntimeError("目标订单 ID 区间已有数据；请指定新的 --start-id，避免覆盖现有数据")

        batch = []
        for row in generate_rows(options):
            batch.append(row)
            summary.add(row)
            if len(batch) >= options.batch_size:
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, batch)
                conn.commit()
                print(f"已写入 {summary.total}/{options.rows}", file=sys.stderr)
                batch.clear()
        if batch:
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, batch)
            conn.commit()
            print(f"已写入 {summary.total}/{options.rows}", file=sys.stderr)
    return summary


def verify(options, expected):
    """Compare the generated batch with persisted rows using full-table counts."""
    from app.db import connect

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(customer_name IS NULL OR TRIM(customer_name) = ''), 0) AS bad_customer, "
                "COALESCE(SUM(order_status IS NULL), 0) AS null_status, "
                "COALESCE(SUM(order_status IS NOT NULL AND CAST(order_status AS BINARY) NOT IN "
                "(CAST(%s AS BINARY), CAST(%s AS BINARY), CAST(%s AS BINARY))), 0) AS bad_status "
                "FROM demo_orders_faker WHERE order_id BETWEEN %s AND %s",
                (*ALLOWED_STATUSES, options.start_id, options.start_id + options.rows - 1),
            )
            row = cur.fetchone()
    actual = {key: int(row[key]) for key in ("total", "bad_customer", "null_status", "bad_status")}
    wanted = {
        "total": expected.total,
        "bad_customer": expected.bad_customer,
        "null_status": expected.null_status,
        "bad_status": expected.bad_status,
    }
    if actual != wanted:
        raise RuntimeError(f"数据库中的批次统计与生成预期不符：实际 {actual}；预期 {wanted}")
    return actual


def rate(value):
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("比例必须在 0 到 1 之间，例如 0.03 表示 3%")
    return number


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成大批量模拟订单；默认只预览，不连接 MySQL")
    parser.add_argument("--rows", type=positive_int, default=10000, help="生成行数，默认 10000")
    parser.add_argument("--seed", type=int, default=20261016, help="随机种子，默认 20261016")
    parser.add_argument("--start-id", type=positive_int, default=1, help="起始订单 ID，默认 1")
    parser.add_argument("--batch-size", type=positive_int, default=1000, help="每批写入行数，默认 1000")
    parser.add_argument("--customer-error-rate", type=rate, default=0.03, help="客户名异常概率，默认 0.03")
    parser.add_argument("--status-error-rate", type=rate, default=0.02, help="状态非法概率，默认 0.02")
    parser.add_argument("--status-null-rate", type=rate, default=0.01, help="状态 NULL 概率，默认 0.01")
    parser.add_argument("--write", action="store_true", help="确认写入 MySQL；省略时只预览")
    parser.add_argument("--verify", action="store_true", help="核对目标 ID 区间在 MySQL 中的实际统计；可单独使用")
    args = parser.parse_args(argv)
    if args.rows > 10_000_000 or args.batch_size > 10_000:
        parser.error("单次最多生成 1000 万行，每批最多 1 万行")
    if args.start_id + args.rows - 1 > 2**63 - 1:
        parser.error("订单 ID 超出 MySQL BIGINT 范围")
    if args.status_error_rate + args.status_null_rate > 1:
        parser.error("状态非法比例与 NULL 比例之和不能超过 1")
    options = Options(
        rows=args.rows, seed=args.seed, start_id=args.start_id, batch_size=args.batch_size,
        customer_error_rate=args.customer_error_rate,
        status_error_rate=args.status_error_rate, status_null_rate=args.status_null_rate,
    )
    try:
        summary = write(options) if args.write else preview(options)
        actual = verify(options, summary) if args.verify else None
    except Exception as exc:
        parser.exit(1, f"生成失败：{exc}\n")
    result = summary.as_dict(options)
    result["mode"] = "written" if args.write else "preview"
    if actual is not None:
        result["database_verification"] = actual
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
